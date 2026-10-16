"""Fixed topic taxonomy shared by every agent, plus keyword heuristics used
for degraded mode and for tagging fetched regulatory documents."""
from __future__ import annotations

import re

TOPICS: dict[str, list[str]] = {
    "aml_risk_assessment": ["risk assessment", "risk-based", "risk based", "risk rating", "risk profile", "higher risk"],
    "customer_due_diligence": ["customer due diligence", "cdd", "know your customer", "kyc", "identity", "identification", "verify", "verification"],
    "enhanced_due_diligence": ["enhanced due diligence", "edd", "high-risk", "high risk", "higher risk"],
    "beneficial_ownership": ["beneficial owner", "ultimate owner", "ownership interest", "controlling interest"],
    "pep": ["politically exposed", "pep"],
    "sanctions": ["sanction", "designated person", "targeted financial", "asset freeze", "un security council"],
    "transaction_monitoring": ["monitoring", "unusual transaction", "ongoing due diligence", "scrutiny"],
    "suspicious_reporting": ["suspicious", "str", "sar", "financial intelligence unit", "fiu", "financial monitoring unit", "report"],
    "tipping_off": ["tipping-off", "tipping off", "disclos"],
    "record_keeping": ["record", "retain", "retention", "keep"],
    "wire_transfers": ["wire transfer", "originator", "beneficiary information", "payment message"],
    "correspondent_banking": ["correspondent", "respondent bank", "shell bank", "nested"],
    "training": ["training", "awareness", "employee screening"],
    "governance": ["board", "senior management", "approve", "oversight", "compliance officer", "internal audit", "independent audit"],
    "credit_risk": ["credit risk", "loan", "lending", "borrower", "collateral", "provision", "default", "exposure"],
    "large_exposures": ["large exposure", "concentration", "connected counterpart"],
    "capital_adequacy": ["capital", "risk-weighted", "tier 1", "cet1"],
    "liquidity_risk": ["liquidity", "lcr", "nsfr", "funding", "high-quality liquid"],
    "operational_risk": ["operational risk", "business continuity", "outsourcing", "incident", "loss event"],
    "it_cyber_security": ["cyber", "information security", "it security", "access control", "encryption", "penetration"],
    "data_privacy": ["personal data", "privacy", "data subject", "consent", "data protection", "confidential"],
    "consumer_protection": ["consumer", "complaint", "fair treatment", "disclosure", "fees", "charges", "grievance"],
    "outsourcing": ["outsourc", "third party", "third-party", "vendor", "service provider"],
    "fraud": ["fraud"],
    "other": [],
}

TOPIC_LIST: list[str] = list(TOPICS)

POLICY_TYPE_TOPICS: dict[str, list[str]] = {
    "AML/KYC": [
        "aml_risk_assessment", "customer_due_diligence", "enhanced_due_diligence", "beneficial_ownership", "pep",
        "transaction_monitoring", "suspicious_reporting", "tipping_off", "record_keeping", "training", "governance",
    ],
    "Credit risk": ["credit_risk", "large_exposures", "capital_adequacy", "governance"],
    "Data privacy": ["data_privacy", "it_cyber_security", "outsourcing", "governance"],
    "Operational risk": ["operational_risk", "it_cyber_security", "outsourcing", "fraud", "governance"],
    "Liquidity": ["liquidity_risk", "governance"],
    "Consumer protection": ["consumer_protection", "data_privacy", "governance"],
    "Other": ["governance"],
}

MODAL_RE = re.compile(r"\b(shall|must|will|should|may|required|requires|prohibited|not permitted|ensure)\b", re.I)
DEF_RE = re.compile(r"^\s*(?:\S+\s+)?[\"“][^\"”]{1,80}[\"”]\s+(means|includes|refers to)\b", re.I)
PROHIB_RE = re.compile(r"\b(shall not|must not|may not|prohibited|not permitted|never)\b", re.I)


def normalize_topics(topics: list[str] | None) -> list[str]:
    out: list[str] = []
    for t in topics or []:
        key = str(t).strip().lower().replace(" ", "_").replace("-", "_")
        if key in TOPICS and key not in out:
            out.append(key)
    return out


def keyword_topics(text: str, limit: int = 3) -> list[str]:
    low = text.lower()
    scored = []
    for topic, kws in TOPICS.items():
        score = sum(low.count(k) for k in kws)
        if score:
            scored.append((score, topic))
    scored.sort(reverse=True)
    return [t for _, t in scored[:limit]]


def heuristic_tag(text: str) -> tuple[list[str], bool, str]:
    """Fallback tagging: (topics, substantive, obligation_type)."""
    if DEF_RE.search(text):
        return keyword_topics(text) or ["other"], False, "definition"
    modal = MODAL_RE.search(text)
    words = len(text.split())
    substantive = bool(modal) and words >= 6
    if PROHIB_RE.search(text):
        ot = "prohibition"
    elif re.search(r"\b(shall|must|will|required)\b", text, re.I):
        ot = "must"
    elif re.search(r"\b(should|may)\b", text, re.I):
        ot = "should"
    else:
        ot = "other"
    return keyword_topics(text) or ["other"], substantive, ot
