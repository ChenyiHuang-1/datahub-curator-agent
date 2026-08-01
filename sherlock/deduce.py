"""Deduction engine — LLM reasoning over an evidence bundle.

Produces grounded deductions: table purpose, column descriptions, inferred
owner, PII suspects. Every deduction cites its evidence and carries a
confidence score. Works with any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import httpx

from .investigate import EvidenceBundle

SYSTEM_PROMPT = """You are Sherlock, a metadata detective. You are given a dossier of \
EVIDENCE about a neglected database table: its schema, lineage, real SQL queries that \
reference it, and sibling table names.

Deduce, strictly grounded in the evidence (never invent):
1. table_description: 2-4 sentences on what this table contains and its business purpose. \
Cite evidence inline like (evidence: joins to orders table in Q3 query).
2. column_descriptions: map of fieldPath -> one-sentence description. Only include columns \
you can describe with reasonable confidence from name/type/queries/lineage.
3. inferred_owner: who most plausibly owns this table (query authors, upstream owners). \
null if no signal.
4. pii_suspects: list of {field, reason} for columns likely containing personal data \
(emails, names, phones, addresses, national IDs, precise location).
5. confidence: 0.0-1.0 overall confidence.
6. reasoning: one short paragraph of your deduction chain.

Respond with ONLY a JSON object with exactly those keys."""


@dataclass
class Deduction:
    table_description: str = ""
    column_descriptions: dict[str, str] = field(default_factory=dict)
    inferred_owner: str | None = None
    pii_suspects: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""
    raw: str = ""


def _endpoint() -> tuple[str, str, str]:
    base = os.environ.get("SHERLOCK_LLM_BASE_URL", "https://api.openai.com/v1")
    key = os.environ.get("SHERLOCK_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("SHERLOCK_LLM_MODEL", "gpt-4o-mini")
    if not key:
        raise SystemExit(
            "No LLM configured. Set SHERLOCK_LLM_API_KEY (and optionally "
            "SHERLOCK_LLM_BASE_URL / SHERLOCK_LLM_MODEL)."
        )
    return base, key, model


def deduce(evidence: EvidenceBundle) -> Deduction:
    base, key, model = _endpoint()
    resp = httpx.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": evidence.to_prompt()},
            ],
            "temperature": 0.2,
        },
        timeout=120,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _parse(text)


def _parse(text: str) -> Deduction:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return Deduction(raw=text, reasoning="unparseable LLM output")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return Deduction(raw=text, reasoning="unparseable JSON")
    return Deduction(
        table_description=str(d.get("table_description", "")),
        column_descriptions={str(k): str(v) for k, v in (d.get("column_descriptions") or {}).items()},
        inferred_owner=d.get("inferred_owner"),
        pii_suspects=list(d.get("pii_suspects") or []),
        confidence=float(d.get("confidence") or 0),
        reasoning=str(d.get("reasoning", "")),
        raw=text,
    )
