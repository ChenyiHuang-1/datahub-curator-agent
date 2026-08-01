"""Patrol scanner — finds 'cold cases': neglected datasets in the graph.

A cold case is a dataset with missing ownership, missing documentation,
or largely undocumented columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import json

from .mcp_client import DataHubMCP


@dataclass
class ColdCase:
    urn: str
    name: str
    platform: str
    missing: list[str] = field(default_factory=list)  # e.g. ["owner", "description", "column_docs"]
    entity: dict[str, Any] = field(default_factory=dict)

    @property
    def case_id(self) -> str:
        return self.urn.split(",")[-2].split(".")[-1] if "," in self.urn else self.name


def _get(d: dict, *path, default=None):
    cur: Any = d
    for p in path:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return default
    return cur if cur is not None else default


def find_cold_cases(mcp: DataHubMCP, limit: int = 20, query: str = "*") -> list[ColdCase]:
    """Scan datasets and diagnose which ones are neglected."""
    res = mcp.call(
        "search",
        query=query,
        filter="entity_type = dataset",
        num_results=limit,
    )
    hits = res.get("results", res) if isinstance(res, dict) else res
    if isinstance(hits, dict):
        hits = hits.get("searchResults", hits.get("entities", []))

    urns: list[str] = []
    for h in hits:
        if isinstance(h, str):
            urns.append(h)
        elif isinstance(h, dict):
            urn = h.get("urn") or _get(h, "entity", "urn")
            if urn:
                urns.append(urn)
    if not urns:
        return []

    cases: list[ColdCase] = []
    details = mcp.call("get_entities", urns=urns[:limit])
    entities = details.get("entities", details) if isinstance(details, dict) else details
    if isinstance(entities, dict):
        entities = list(entities.values())

    for ent in entities:
        if not isinstance(ent, dict):
            continue
        urn = ent.get("urn", "")
        name = _get(ent, "name") or urn.split(",")[-2] if "," in urn else urn
        platform = _get(ent, "platform", "name") or (urn.split(":")[3].split(",")[0] if urn.count(":") >= 3 else "?")

        missing: list[str] = []
        owners = _get(ent, "ownership", "owners", default=[]) or _get(ent, "owners", default=[])
        if not owners:
            missing.append("owner")
        desc = _get(ent, "description") or _get(ent, "properties", "description") or _get(ent, "editableProperties", "description")
        if not desc or not str(desc).strip():
            missing.append("description")

        fields = _get(ent, "schema", "fields", default=[]) or _get(ent, "schemaMetadata", "fields", default=[]) or []
        if fields:
            undocumented = [f for f in fields if not (f.get("description") or "").strip()]
            if len(undocumented) > len(fields) / 2:
                missing.append(f"column_docs ({len(undocumented)}/{len(fields)} undocumented)")

        if missing:
            cases.append(ColdCase(urn=urn, name=str(name), platform=str(platform), missing=missing, entity=ent))

    return cases
