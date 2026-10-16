"""Regenerate frontend/mock/result.json from samples/sample_aml_policy.txt.

Offsets are computed in code (never by hand) so the mock always lines up with
the sample text. The citations are short excerpts of the FATF
Recommendations, used only to make the offline demo realistic.

Run:  python scripts/build_mock_result.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.tools.clauses import split_clauses  # noqa: E402

FATF = {
    "doc_id": "fatf-recommendations",
    "source_title": "The FATF Recommendations",
    "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html",
}

# quote_from_policy, gap_type, severity, title, explanation, citation(section, quote, chunk), fix, rationale, verification
SPECS = [
    (
        "may be verified within 90 days after the account is opened where the branch manager considers it appropriate",
        "INSUFFICIENT", "high",
        "Delayed verification window is long and discretionary",
        "Verification after onboarding is only acceptable as an exception, completed as soon as reasonably practicable and with risk controls. A fixed 90-day window left to branch discretion goes beyond that exception.",
        ("Interpretive Note to Recommendation 10", "this occurs as soon as reasonably practicable", "0031"),
        "3.2 Where verification cannot be completed before the relationship is established, it shall be completed as soon as reasonably practicable and in any case within 10 business days, subject to transaction limits approved by the Compliance Officer and documented risk-management procedures.",
        "Aligns delayed verification with the narrow exception and removes branch-level discretion.",
        ("verified", None),
    ),
    (
        "only where a single natural person holds more than 50 percent of the ownership interest",
        "INSUFFICIENT", "medium",
        "Beneficial ownership threshold is too high",
        "A 50 percent threshold means owners with substantial but minority control are never identified. The standard gives a materially lower controlling-interest example.",
        ("Interpretive Note to Recommendation 10", "more than a certain percentage of the company (e.g. 25%)", "0034"),
        "3.3 The Bank will identify and take reasonable measures to verify every natural person who holds 25 percent or more of the ownership interest of a legal person, or who otherwise exercises control over it.",
        "Lowers the threshold and adds control by other means.",
        ("verified", None),
    ),
    (
        "Enhanced due diligence may be applied to customers that staff consider to be higher risk, based on their own judgement and experience.",
        "AMBIGUOUS", "medium",
        "Enhanced due diligence is optional and its triggers are undefined",
        "The clause makes EDD discretionary and does not say which risk factors require it. Higher-risk relationships must receive enhanced measures under a documented risk assessment.",
        ("Recommendation 1", "identify, assess and take effective action to mitigate their money laundering", "0004"),
        "3.4 The Bank shall apply enhanced due diligence to every customer rated high risk under the Bank's documented customer risk assessment methodology, including the risk factors listed in Annex A.",
        "Makes EDD mandatory for high-risk customers and anchors it to a documented methodology.",
        ("verified", None),
    ),
    (
        "staff consider to be higher risk, based on their own judgement and experience",
        "INSUFFICIENT", "low",
        "Risk rating depends on individual judgement",
        "Risk ratings based only on personal judgement are not reproducible or auditable. A documented, institution-wide risk assessment is expected.",
        ("Recommendation 1", "identify, assess and take effective action to mitigate their money laundering", "0004"),
        "Customer risk ratings shall be assigned using the Bank's approved risk scoring model and recorded in the core banking system.",
        "Replaces individual judgement with an approved, auditable model.",
        ("partial", "Source supports a risk-based approach but not a specific scoring model."),
    ),
    (
        "may be opened by the relationship manager after completing the standard customer due diligence process",
        "CONTRADICTION", "high",
        "PEP accounts opened without senior management approval",
        "Relationships with politically exposed persons require senior management approval and additional measures. Standard due diligence and relationship-manager sign-off contradict this.",
        ("Recommendation 12", "obtain senior management approval for establishing", "0058"),
        "4.1 Accounts for politically exposed persons shall be opened only with the approval of senior management, after enhanced due diligence including reasonable measures to establish the source of wealth and source of funds.",
        "Adds senior approval and source-of-wealth checks required for PEPs.",
        ("verified", None),
    ),
    (
        "periodically as resources permit",
        "AMBIGUOUS", "medium",
        "Ongoing monitoring frequency is undefined",
        "Reviews tied to available resources have no defined frequency, so ongoing due diligence can lapse entirely.",
        ("Recommendation 10", "ongoing due diligence on the business relationship and scrutiny of transactions", "0029"),
        "5.1 The Bank will review customer profiles and supporting documents at least annually for high-risk customers, every two years for medium-risk customers and every three years for low-risk customers, and upon any trigger event.",
        "Sets a risk-based review cycle that does not depend on resources.",
        ("verified", None),
    ),
    (
        "for at least three years after the date of the transaction",
        "CONTRADICTION", "high",
        "Record retention period is shorter than required",
        "Transaction records must be kept for at least five years. Three years falls short of the minimum.",
        ("Recommendation 11", "maintain, for at least five years, all necessary records on transactions", "0047"),
        "6.1 The Bank will retain records of all domestic and international transactions for at least five years after the date of the transaction, or longer where required by law or a competent authority.",
        "Extends retention to the five-year minimum.",
        ("verified", None),
    ),
    (
        "who will decide whether to inform the Financial Monitoring Unit within a reasonable time",
        "INSUFFICIENT", "high",
        "Suspicious transaction reporting is not prompt",
        "Suspicions must be reported promptly to the financial intelligence unit. 'Within a reasonable time' and an internal discretion step dilute that duty.",
        ("Recommendation 20", "report promptly its suspicions to the financial intelligence unit (FIU)", "0081"),
        "7.1 Staff shall report suspicious transactions to the Compliance Officer immediately. The Compliance Officer shall file a suspicious transaction report with the Financial Monitoring Unit promptly and without delay once suspicion is formed.",
        "Requires prompt filing with the FIU.",
        ("verified", None),
    ),
    (
        None,  # MISSING, anchored at end of section 7
        "MISSING", "high",
        "No prohibition on tipping-off",
        "The policy never prohibits staff from disclosing that a suspicious transaction report has been or will be filed. This obligation is absent from the draft.",
        ("Recommendation 21", "prohibited by law from disclosing (“tipping-off”) the fact", "0084"),
        "7.2 No director, officer or employee shall disclose to the customer or any third party that a suspicious transaction report or related information is being, or has been, filed with the Financial Monitoring Unit.",
        "Adds the tipping-off prohibition as a new clause.",
        ("verified", None),
    ),
    (
        "at the time of joining the Bank",
        "INSUFFICIENT", "low",
        "Training is one-off rather than ongoing",
        "Programmes against money laundering are expected to include ongoing employee training, not only induction training.",
        ("Interpretive Note to Recommendation 18", "an ongoing employee training programme", "0072"),
        "8.1 All staff will receive anti-money laundering training on joining the Bank and refresher training at least annually, with role-specific training for front-line and compliance staff.",
        "Adds annual refresher and role-based training.",
        ("verified", None),
    ),
]


def main() -> None:
    text = (ROOT / "samples" / "sample_aml_policy.txt").read_text(encoding="utf-8")
    clauses = split_clauses(text)
    findings, table = [], []
    for i, spec in enumerate(SPECS, start=1):
        quote, gap, sev, title, expl, (sec, cq, cnum), fix, why, (vst, vnote) = spec
        if quote is None:
            anchor_clause = next(c for c in clauses if c.text.startswith("7.1"))
            start = end = anchor_clause.end
            clause_ids: list[str] = []
            clause_ref = "After 7. Reporting"
        else:
            start = text.index(quote)
            end = start + len(quote)
            hit = [c for c in clauses if c.start <= start and c.end >= end]
            clause_ids = [c.id for c in hit]
            clause_ref = ", ".join(c.label or c.id for c in hit)
        fid = f"F{i}"
        findings.append({
            "id": fid,
            "clause_ids": clause_ids,
            "span": {"start": start, "end": end},
            "gap_type": gap,
            "severity": sev,
            "title": title,
            "explanation": expl,
            "citations": [{**FATF, "chunk_id": f"fatf-recommendations:{cnum}", "quote": cq, "section": sec}],
            "suggestion": {"text": fix, "rationale": why},
            "verification": {"status": vst, "note": vnote},
            "inference_notes": [],
        })
        table.append({
            "finding_id": fid, "clause_ref": clause_ref, "gap_type": gap, "severity": sev,
            "issue": title, "source": f"{FATF['source_title']}, {sec}", "fix": fix,
        })

    findings[4]["inference_notes"] = ["Supervisors in the region have recently focused on PEP onboarding controls."]
    result = {
        "run_id": "mock-run",
        "meta": {
            "country": "PK", "region": "Punjab", "city": None, "timezone": "Asia/Karachi",
            "as_of": "2026-10-16", "policy_type": "AML/KYC", "institution_type": "Commercial bank",
            "generated_at": "2026-10-16T12:00:00+05:00",
            "jurisdiction_chain": ["PK/Punjab", "PK", "global"],
        },
        "policy": {
            "filename": "sample_aml_policy.txt",
            "full_text": text,
            "clauses": [c.model_dump() for c in clauses],
        },
        "findings": findings,
        "gap_table": table,
        "coverage": {"obligations_total": 14, "met": 5, "partial": 6, "missing": 3},
        "sources": [
            {"doc_id": "fatf-recommendations", "title": FATF["source_title"], "issuer": "Financial Action Task Force",
             "url": FATF["source_url"], "jurisdiction": "global"},
            {"doc_id": "basel-core-principles", "title": "Core Principles for Effective Banking Supervision",
             "issuer": "Basel Committee on Banking Supervision", "url": "https://www.bis.org/bcbs/publ/d573.htm",
             "jurisdiction": "global"},
        ],
        "stats": {"tokens_in": 52140, "tokens_out": 9310, "llm_calls": 21, "duration_s": 74.2,
                  "web_searches": 0, "cache_hits": 0, "reduced_mode": False},
    }
    out = ROOT / "frontend" / "mock" / "result.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(findings)} findings, {len(clauses)} clauses")


if __name__ == "__main__":
    main()
