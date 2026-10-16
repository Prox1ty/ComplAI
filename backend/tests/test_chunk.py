from backend.tools.chunk import MAX_TOKENS, chunk_text, estimate_tokens


def _doc():
    para = ("Financial institutions should maintain records of transactions and identification data and make them "
            "available to competent authorities upon request in a timely manner. ") * 6
    parts = ["PART I GENERAL"]
    for i in range(1, 6):
        parts.append(f"Section {i} Requirements")
        parts.append(para)
        parts.append(para)
    return "\n\n".join(parts)


def test_chunks_respect_budget_and_carry_heading_path():
    chunks = chunk_text(_doc(), {"doc_id": "d1", "jurisdiction": "global", "topics": ["record_keeping"]})
    assert len(chunks) >= 5
    for c in chunks:
        assert estimate_tokens(c.text) <= MAX_TOKENS + 5
        assert c.metadata["doc_id"] == "d1"
        assert c.metadata["jurisdiction"] == "global"
        assert c.text.startswith(c.metadata["section"])
    assert chunks[0].metadata["section"].startswith("PART I GENERAL > Section 1")
    assert len({c.id for c in chunks}) == len(chunks)


def test_overlap_between_consecutive_chunks_in_a_section():
    chunks = [c for c in chunk_text(_doc(), {"doc_id": "d1"}) if c.metadata["section"].endswith("Section 1 Requirements")]
    assert len(chunks) >= 2
    tail = chunks[0].text.split()[-5:]
    assert " ".join(tail) in chunks[1].text
