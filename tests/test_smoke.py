"""Offline smoke test for Sherlock's deduction pipeline.

Runs the evidence → prompt → parse path with a canned LLM response, so CI can
verify the pipeline without a DataHub instance or an LLM key.
"""

from __future__ import annotations

import json

from sherlock.deduce import _parse
from sherlock.investigate import EvidenceBundle
from sherlock.patrol import ColdCase
from sherlock.scribe import render_case_report, WriteReceipt


def test_prompt_rendering():
    case = ColdCase(
        urn="urn:li:dataset:(urn:li:dataPlatform:postgres,shop.analytics.cust_ltv_v3,PROD)",
        name="cust_ltv_v3",
        platform="postgres",
        missing=["owner", "description"],
    )
    ev = EvidenceBundle(
        case=case,
        schema_fields=[{"fieldPath": "em", "type": "varchar"}],
        queries=[{"statement": "SELECT em FROM cust_ltv_v3", "actor": "bob.finance"}],
    )
    prompt = ev.to_prompt()
    assert "cust_ltv_v3" in prompt
    assert "bob.finance" in prompt
    assert "em (varchar)" in prompt


def test_parse_deduction():
    canned = json.dumps(
        {
            "table_description": "Customer lifetime value aggregates (evidence: LTV columns, joins to customers).",
            "column_descriptions": {"em": "Customer email address (evidence: joined to customers.email)."},
            "inferred_owner": "bob.finance",
            "pii_suspects": [{"field": "em", "reason": "email address"}],
            "confidence": 0.85,
            "reasoning": "Queries by bob.finance aggregate ltv_365d; em joins to customers.email.",
        }
    )
    d = _parse(canned)
    assert d.confidence == 0.85
    assert d.inferred_owner == "bob.finance"
    assert d.pii_suspects[0]["field"] == "em"


def test_case_report():
    case = ColdCase(urn="urn:x", name="t", platform="pg", missing=["owner"])
    ev = EvidenceBundle(case=case)
    d = _parse('{"table_description":"x","confidence":0.9,"reasoning":"r","pii_suspects":[],"column_descriptions":{}}')
    r = WriteReceipt()
    r.note("test action")
    report = render_case_report(ev, d, r)
    assert "Case Report" in report and "test action" in report


if __name__ == "__main__":
    test_prompt_rendering()
    test_parse_deduction()
    test_case_report()
    print("all smoke tests passed ✓")
