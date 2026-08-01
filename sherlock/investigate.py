"""Investigator — gathers evidence about a cold case from the DataHub graph."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .mcp_client import DataHubMCP
from .patrol import ColdCase


@dataclass
class EvidenceBundle:
    case: ColdCase
    schema_fields: list[dict] = field(default_factory=list)
    upstream: list[dict] = field(default_factory=list)
    downstream: list[dict] = field(default_factory=list)
    queries: list[dict] = field(default_factory=list)
    siblings: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        """Render the evidence into a compact textual dossier for the LLM."""
        parts = [
            f"# Case dossier: {self.case.name}",
            f"URN: {self.case.urn}",
            f"Platform: {self.case.platform}",
            f"Missing metadata: {', '.join(self.case.missing)}",
            "",
            "## Schema fields",
        ]
        for f in self.schema_fields[:60]:
            fp = f.get("fieldPath") or f.get("path") or "?"
            ft = f.get("type") or f.get("nativeDataType") or "?"
            fd = (f.get("description") or "").strip()
            parts.append(f"- {fp} ({ft}){' — ' + fd if fd else ''}")
        parts.append("")
        parts.append("## Upstream lineage (data sources)")
        for u in self.upstream[:15]:
            parts.append(f"- {json.dumps(u, default=str)[:300]}")
        parts.append("## Downstream lineage (consumers)")
        for d in self.downstream[:15]:
            parts.append(f"- {json.dumps(d, default=str)[:300]}")
        parts.append("")
        parts.append("## Real SQL queries referencing this table")
        for q in self.queries[:10]:
            stmt = q.get("statement") or q.get("query") or json.dumps(q, default=str)
            actor = q.get("actor") or q.get("createdBy") or "unknown"
            parts.append(f"### by {actor}\n```sql\n{str(stmt)[:800]}\n```")
        parts.append("")
        parts.append("## Sibling tables on the same platform (naming context)")
        for s in self.siblings[:20]:
            parts.append(f"- {s}")
        return "\n".join(parts)


def _as_list(res: Any, *keys: str) -> list:
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        for k in keys:
            v = res.get(k)
            if isinstance(v, list):
                return v
        # nested one level
        for v in res.values():
            if isinstance(v, dict):
                for k in keys:
                    if isinstance(v.get(k), list):
                        return v[k]
    return []


def investigate(mcp: DataHubMCP, case: ColdCase) -> EvidenceBundle:
    ev = EvidenceBundle(case=case)

    # 1. schema fields
    try:
        res = mcp.call("list_schema_fields", urn=case.urn)
        ev.schema_fields = _as_list(res, "fields", "schemaFields", "results")
    except Exception:
        fields = case.entity.get("schema", {}).get("fields") if isinstance(case.entity.get("schema"), dict) else None
        ev.schema_fields = fields or []

    # 2. lineage both directions
    for is_upstream, target in ((True, "upstream"), (False, "downstream")):
        try:
            res = mcp.call("get_lineage", urn=case.urn, upstream=is_upstream, max_hops=2)
            setattr(ev, target, _as_list(res, "entities", "results", "lineage"))
        except Exception as e:
            setattr(ev, target, [{"error": str(e)[:200]}])

    # 3. real queries
    try:
        res = mcp.call("get_dataset_queries", urn=case.urn)
        ev.queries = _as_list(res, "queries", "results")
    except Exception:
        ev.queries = []

    # 4. sibling tables for naming conventions
    try:
        res = mcp.call(
            "search",
            query="*",
            filter=f"entity_type = dataset AND platform = {case.platform}",
            num_results=20,
        )
        hits = _as_list(res, "results", "searchResults", "entities")
        names = []
        for h in hits:
            if isinstance(h, dict):
                n = h.get("name") or h.get("urn", "")
                if n and n != case.urn:
                    names.append(str(n))
        ev.siblings = names
    except Exception:
        ev.siblings = []

    return ev
