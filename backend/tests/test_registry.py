from backend.schemas import DocMeta
from backend.tools.registry import Registry, doc_id_for_url, normalize_url, resolve_jurisdictions


def test_resolve_chain():
    assert resolve_jurisdictions("PK", "Punjab") == ["PK/Punjab", "PK", "global"]
    assert resolve_jurisdictions("us", "NY", "New York") == ["US/NY/New York", "US/NY", "US", "global"]
    assert resolve_jurisdictions("DE") == ["DE", "EU", "global"]
    assert resolve_jurisdictions("AE", "Dubai") == ["AE/Dubai", "AE", "GCC", "global"]


def test_url_normalisation():
    assert normalize_url("HTTPS://WWW.Example.gov/a/?utm_source=x&b=2#frag") == "https://www.example.gov/a?b=2"
    assert doc_id_for_url("https://x.gov/a/") == doc_id_for_url("https://x.gov/a")


def test_add_and_lookup(tmp_path):
    reg = Registry(tmp_path)
    reg.add_doc(DocMeta(doc_id="a", title="A", url="https://a", jurisdiction="global", topics=["pep", "training"], content_hash="h1"))
    reg.add_doc(DocMeta(doc_id="b", title="B", url="https://b", jurisdiction="PK", topics=["pep"]))
    reg.add_doc(DocMeta(doc_id="c", title="C", url="https://c", jurisdiction="IN", topics=["pep"]))
    chain = ["PK/Punjab", "PK", "global"]
    assert {d.doc_id for d in reg.get_docs(chain)} == {"a", "b"}
    assert [d.doc_id for d in reg.get_docs(chain, ["training"])] == ["a"]
    assert reg.topic_coverage(chain, ["pep", "training", "sanctions"]) == {"pep": 2, "training": 1, "sanctions": 0}
    assert reg.find_by_hash("h1").doc_id == "a"
    reg.set_obligations("a", "[]")
    reg.add_doc(DocMeta(doc_id="a", title="A2", url="https://a", jurisdiction="global", topics=["pep"]))
    assert reg.get_doc("a").obligations_json == "[]"  # obligations survive metadata refresh
    assert (tmp_path / "registry.json").exists()
