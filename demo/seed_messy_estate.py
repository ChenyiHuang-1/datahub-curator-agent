"""Seed the quickstart DataHub with a realistic 'messy' e-commerce data estate.

Creates datasets with deliberate metadata neglect — missing owners, missing
descriptions, undocumented columns, PII columns without tags — plus lineage
and sample queries, so Sherlock has real evidence to investigate.

Usage:
    python demo/seed_messy_estate.py  (DATAHUB_GMS_URL defaults to http://localhost:8080)
"""

from __future__ import annotations

import os
import time

from datahub.emitter.mce_builder import make_data_platform_urn, make_dataset_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    OtherSchemaClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    NumberTypeClass,
    TimeTypeClass,
    UpstreamClass,
    UpstreamLineageClass,
)

GMS = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
PLATFORM = "postgres"
NOW = AuditStampClass(time=int(time.time() * 1000), actor="urn:li:corpuser:datahub")


def field(path: str, ftype, native: str, desc: str | None = None) -> SchemaFieldClass:
    return SchemaFieldClass(
        fieldPath=path,
        type=SchemaFieldDataTypeClass(type=ftype()),
        nativeDataType=native,
        description=desc,
    )


S = StringTypeClass
N = NumberTypeClass
T = TimeTypeClass

# (name, description, owner, fields) — None description/owner = neglected
TABLES: list[tuple[str, str | None, str | None, list[SchemaFieldClass]]] = [
    (
        "shop.public.customers",
        "Registered customer master data for the storefront.",
        "alice",
        [
            field("customer_id", N, "bigint", "Primary key."),
            field("email", S, "varchar", "Customer email address."),
            field("full_name", S, "varchar", "Customer display name."),
            field("created_at", T, "timestamp", "Signup timestamp."),
        ],
    ),
    (
        "shop.public.orders",
        "One row per customer order, written by the checkout service.",
        "alice",
        [
            field("order_id", N, "bigint", "Primary key."),
            field("customer_id", N, "bigint", "FK to customers."),
            field("total_cents", N, "bigint", "Order total in cents."),
            field("placed_at", T, "timestamp", "Checkout timestamp."),
        ],
    ),
    # ---- the cold cases ----
    (
        "shop.analytics.cust_ltv_v3",  # cryptic name, no docs, no owner, PII inside
        None,
        None,
        [
            field("cid", N, "bigint"),
            field("em", S, "varchar"),
            field("ltv_180d", N, "numeric"),
            field("ltv_365d", N, "numeric"),
            field("last_order_ts", T, "timestamp"),
            field("phone_backup", S, "varchar"),
            field("seg", S, "varchar"),
        ],
    ),
    (
        "shop.analytics.daily_rev_agg",  # no owner, no table doc, half columns undocumented
        None,
        None,
        [
            field("day", T, "date"),
            field("gross_rev", N, "numeric"),
            field("net_rev", N, "numeric"),
            field("order_cnt", N, "bigint"),
            field("aov", N, "numeric"),
        ],
    ),
    (
        "shop.staging.tmp_cust_export_fix2",  # scary orphan staging table w/ PII
        None,
        None,
        [
            field("row_id", N, "bigint"),
            field("email_addr", S, "varchar"),
            field("full_nm", S, "varchar"),
            field("home_addr", S, "varchar"),
            field("dob", T, "date"),
        ],
    ),
]

LINEAGE = {
    "shop.analytics.cust_ltv_v3": ["shop.public.customers", "shop.public.orders"],
    "shop.analytics.daily_rev_agg": ["shop.public.orders"],
    "shop.staging.tmp_cust_export_fix2": ["shop.public.customers"],
}

QUERIES = [
    (
        "shop.analytics.cust_ltv_v3",
        "bob.finance",
        "SELECT seg, avg(ltv_365d) AS avg_ltv FROM shop.analytics.cust_ltv_v3 "
        "WHERE last_order_ts > now() - interval '90 days' GROUP BY seg ORDER BY avg_ltv DESC;",
    ),
    (
        "shop.analytics.cust_ltv_v3",
        "bob.finance",
        "SELECT c.full_name, l.ltv_365d FROM shop.analytics.cust_ltv_v3 l "
        "JOIN shop.public.customers c ON c.customer_id = l.cid WHERE l.ltv_365d > 100000;",
    ),
    (
        "shop.analytics.daily_rev_agg",
        "carol.exec",
        "SELECT day, gross_rev, net_rev FROM shop.analytics.daily_rev_agg "
        "WHERE day >= date_trunc('quarter', current_date) ORDER BY day;",
    ),
]


def urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env="PROD")


def main() -> None:
    emitter = DatahubRestEmitter(gms_server=GMS, extra_headers={})
    emitter.test_connection()
    print(f"Connected to {GMS}")

    for name, desc, owner, fields in TABLES:
        u = urn(name)
        mcps = [
            MetadataChangeProposalWrapper(
                entityUrn=u,
                aspect=SchemaMetadataClass(
                    schemaName=name,
                    platform=make_data_platform_urn(PLATFORM),
                    version=0,
                    hash="",
                    platformSchema=OtherSchemaClass(rawSchema=""),
                    fields=fields,
                ),
            )
        ]
        if desc:
            mcps.append(
                MetadataChangeProposalWrapper(
                    entityUrn=u,
                    aspect=DatasetPropertiesClass(description=desc, name=name.split(".")[-1]),
                )
            )
        if owner:
            mcps.append(
                MetadataChangeProposalWrapper(
                    entityUrn=u,
                    aspect=OwnershipClass(
                        owners=[OwnerClass(owner=make_user_urn(owner), type=OwnershipTypeClass.TECHNICAL_OWNER)]
                    ),
                )
            )
        for m in mcps:
            emitter.emit(m)
        print(f"seeded {name}  (neglected={'yes' if not desc else 'no'})")

    for downstream, ups in LINEAGE.items():
        emitter.emit(
            MetadataChangeProposalWrapper(
                entityUrn=urn(downstream),
                aspect=UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(dataset=urn(u_), type=DatasetLineageTypeClass.TRANSFORMED, auditStamp=NOW)
                        for u_ in ups
                    ]
                ),
            )
        )
        print(f"lineage {downstream} <- {ups}")

    # sample queries via query entity (best-effort; API varies by version)
    try:
        from datahub.metadata.schema_classes import (
            QueryLanguageClass,
            QueryPropertiesClass,
            QuerySourceClass,
            QueryStatementClass,
            QuerySubjectClass,
            QuerySubjectsClass,
        )

        for i, (tbl, author, sql) in enumerate(QUERIES):
            qurn = f"urn:li:query:sherlock-demo-{i}"
            emitter.emit(
                MetadataChangeProposalWrapper(
                    entityUrn=qurn,
                    aspect=QueryPropertiesClass(
                        statement=QueryStatementClass(value=sql, language=QueryLanguageClass.SQL),
                        source=QuerySourceClass.MANUAL,
                        created=AuditStampClass(time=NOW.time, actor=make_user_urn(author)),
                        lastModified=AuditStampClass(time=NOW.time, actor=make_user_urn(author)),
                    ),
                )
            )
            emitter.emit(
                MetadataChangeProposalWrapper(
                    entityUrn=qurn,
                    aspect=QuerySubjectsClass(subjects=[QuerySubjectClass(entity=urn(tbl))]),
                )
            )
        print(f"seeded {len(QUERIES)} sample queries")
    except ImportError as e:
        print(f"query seeding skipped: {e}")

    print("Done. The estate is suitably messy. 🕵️")


if __name__ == "__main__":
    main()
