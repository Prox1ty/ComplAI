"""Source quality heuristics for web results, plus regulator and language hints
used when generating search queries."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from backend.schemas import SearchHit

GLOBAL_DOMAINS = {
    "bis.org", "fatf-gafi.org", "imf.org", "worldbank.org", "fsb.org", "iosco.org", "oecd.org", "egmontgroup.org",
    "unodc.org", "un.org", "wolfsberg-principles.com",
}
BLOC_DOMAINS = {"eur-lex.europa.eu": "EU", "eba.europa.eu": "EU", "ecb.europa.eu": "EU", "esma.europa.eu": "EU", "gcc-sg.org": "GCC"}
REGULATOR_DOMAINS = {
    "sbp.org.pk", "secp.gov.pk", "fmu.gov.pk", "federalreserve.gov", "occ.gov", "occ.treas.gov", "fdic.gov",
    "fincen.gov", "consumerfinance.gov", "dfs.ny.gov", "ncua.gov", "fca.org.uk", "bankofengland.co.uk",
    "legislation.gov.uk", "rbi.org.in", "mas.gov.sg", "hkma.gov.hk", "centralbank.ae", "cbuae.gov.ae",
    "sama.gov.sa", "cbb.gov.bh", "qcb.gov.qa", "cbk.gov.kw", "cbo.gov.om", "bafin.de", "bundesbank.de",
    "acpr.banque-france.fr", "bancaditalia.it", "bde.es", "dnb.nl", "centralbank.ie", "apra.gov.au",
    "asic.gov.au", "austrac.gov.au", "osfi-bsif.gc.ca", "fintrac-canafe.gc.ca", "bnm.gov.my", "bot.or.th",
    "ojk.go.id", "bsp.gov.ph", "cbn.gov.ng", "centralbank.go.ke", "resbank.co.za", "fsca.co.za", "bcb.gov.br",
    "banxico.org.mx", "cnbv.gob.mx", "fsa.go.jp", "fss.or.kr", "pbc.gov.cn", "nfra.gov.cn", "cbe.org.eg",
    "bb.org.bd", "cbsl.gov.lk", "dfsa.ae", "adgm.com", "difc.ae", "finma.ch", "fi.se", "finanstilsynet.no",
}
PENALTY_HOSTS = {
    "medium.com", "linkedin.com", "reddit.com", "quora.com", "youtube.com", "facebook.com", "twitter.com", "x.com",
    "scribd.com", "slideshare.net", "wikipedia.org", "investopedia.com",
}
VENDOR_HINTS = re.compile(r"(blog|solutions?|software|vendor|consult|advisory|pricing|demo|product|webinar|newsletter)", re.I)
REGULATOR_HINTS = re.compile(r"(centralbank|central-bank|monetary|sbp|reserve|finance|financial|regulat|supervis|treasury|fiu|authority)", re.I)

REGULATORS: dict[str, list[str]] = {
    "PK": ["State Bank of Pakistan", "Financial Monitoring Unit", "SECP"],
    "US": ["FinCEN", "Federal Reserve", "OCC", "FDIC", "CFPB"],
    "GB": ["Financial Conduct Authority", "Prudential Regulation Authority", "HM Treasury"],
    "IN": ["Reserve Bank of India", "FIU-IND"],
    "AE": ["Central Bank of the UAE", "UAE FIU"],
    "SA": ["Saudi Central Bank (SAMA)"],
    "SG": ["Monetary Authority of Singapore"],
    "HK": ["Hong Kong Monetary Authority"],
    "AU": ["APRA", "AUSTRAC", "ASIC"],
    "CA": ["OSFI", "FINTRAC"],
    "DE": ["BaFin", "Deutsche Bundesbank"],
    "FR": ["ACPR", "Tracfin"],
    "NG": ["Central Bank of Nigeria", "NFIU"],
    "KE": ["Central Bank of Kenya", "Financial Reporting Centre"],
    "ZA": ["South African Reserve Bank", "Financial Intelligence Centre"],
    "MY": ["Bank Negara Malaysia"],
    "BD": ["Bangladesh Bank", "BFIU"],
    "EG": ["Central Bank of Egypt"],
    "BR": ["Banco Central do Brasil", "COAF"],
    "MX": ["CNBV", "Banco de México"],
    "JP": ["Financial Services Agency"],
}
LOCAL_LANGUAGE: dict[str, str] = {
    "PK": "Urdu", "SA": "Arabic", "AE": "Arabic", "QA": "Arabic", "KW": "Arabic", "OM": "Arabic", "BH": "Arabic",
    "EG": "Arabic", "DE": "German", "AT": "German", "FR": "French", "ES": "Spanish", "MX": "Spanish", "IT": "Italian",
    "BR": "Portuguese", "PT": "Portuguese", "JP": "Japanese", "CN": "Chinese", "KR": "Korean", "ID": "Indonesian",
    "TR": "Turkish", "RU": "Russian", "NL": "Dutch", "TH": "Thai", "VN": "Vietnamese", "BD": "Bengali",
}


def host_of(url: str) -> str:
    h = urlsplit(url).netloc.lower().split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def _matches(host: str, domains: set[str] | dict) -> str | None:
    for d in domains:
        if host == d or host.endswith("." + d):
            return d
    return None


def score_source(url: str, title: str = "", snippet: str = "") -> float:
    host = host_of(url)
    path = urlsplit(url).path.lower()
    score = 0.0
    if _matches(host, GLOBAL_DOMAINS) or _matches(host, BLOC_DOMAINS) or _matches(host, REGULATOR_DOMAINS):
        score += 3.0
    if re.search(r"\.(gov|gob|gouv|go|govt|gv)(\.[a-z]{2})?$", host) or host.endswith(".gov") or ".gov." in host:
        score += 2.0
    if REGULATOR_HINTS.search(host):
        score += 1.0
    if path.endswith(".pdf"):
        score += 0.5
    if re.search(r"(regulation|circular|guideline|directive|act|rules|framework|recommendation|standard)", f"{title} {path}", re.I):
        score += 0.5
    if _matches(host, PENALTY_HOSTS):
        score -= 3.0
    if VENDOR_HINTS.search(host) or "/blog" in path:
        score -= 2.0
    return score


def rank_results(hits: list[SearchHit], min_score: float = 0.0) -> list[SearchHit]:
    for h in hits:
        h.score = score_source(h.url, h.title, h.snippet)
    ranked = sorted(hits, key=lambda h: -h.score)
    return [h for h in ranked if h.score >= min_score]


def jurisdiction_for_url(url: str, country_key: str) -> str:
    host = host_of(url)
    if _matches(host, GLOBAL_DOMAINS):
        return "global"
    bloc = _matches(host, BLOC_DOMAINS)
    if bloc:
        return BLOC_DOMAINS[bloc]
    return country_key


def issuer_for_url(url: str) -> str:
    return host_of(url)
