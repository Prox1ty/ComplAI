from backend.schemas import SearchHit
from backend.tools.sources import jurisdiction_for_url, rank_results, score_source


def test_official_sources_outrank_blogs():
    hits = [
        SearchHit(title="AML blog", url="https://medium.com/@x/aml-tips"),
        SearchHit(title="AML Regulations", url="https://www.sbp.org.pk/bprd/2020/C1.pdf"),
        SearchHit(title="KYC software", url="https://kyc-solutions.com/blog/kyc"),
        SearchHit(title="FATF Recommendations", url="https://www.fatf-gafi.org/en/publications/x.html"),
    ]
    ranked = rank_results(hits, min_score=0.5)
    urls = [h.url for h in ranked]
    assert urls[0].startswith("https://www.sbp.org.pk") or urls[0].startswith("https://www.fatf-gafi.org")
    assert all("medium.com" not in u and "kyc-solutions" not in u for u in urls)
    assert score_source("https://www.fincen.gov/resources") > score_source("https://example.com/page")


def test_jurisdiction_inference():
    assert jurisdiction_for_url("https://www.bis.org/bcbs/publ/d573.htm", "PK") == "global"
    assert jurisdiction_for_url("https://eur-lex.europa.eu/eli/reg/2024/1624", "DE") == "EU"
    assert jurisdiction_for_url("https://www.sbp.org.pk/x", "PK") == "PK"
