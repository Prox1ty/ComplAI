from pathlib import Path

from backend.tools.clauses import is_heading, split_clauses

ROOT = Path(__file__).resolve().parents[2]


def test_offsets_are_exact_and_sections_tracked():
    text = (ROOT / "samples" / "sample_aml_policy.txt").read_text(encoding="utf-8")
    clauses = split_clauses(text)
    assert len(clauses) >= 14
    for c in clauses:
        assert text[c.start:c.end] == c.text
    by_label = {c.label: c for c in clauses if c.label}
    assert by_label["3.2"].section == "3. Customer Due Diligence"
    assert by_label["6.1"].text.startswith("6.1 The Bank will retain")
    assert "Record Keeping" not in by_label["6.1"].text  # headings are not clauses


def test_numbering_styles():
    text = (
        "Article 1 Scope\n"
        "Article 2. Banks shall verify the identity of every customer before opening any account or relationship.\n"
        "(a) the verification shall use reliable and independent documents issued by a competent authority;\n"
        "(b) records of verification shall be kept for the period required by law and made available on request;\n"
        "Section 3.1 The compliance officer shall report suspicious transactions promptly to the authority.\n"
    )
    clauses = split_clauses(text)
    labels = [c.label for c in clauses]
    assert labels == ["Article 2", "(a)", "(b)", "Section 3.1"]
    assert clauses[0].section == "Article 1 Scope"


def test_short_unnumbered_fragments_merge_into_previous():
    text = (
        "1. The Bank shall keep records of all transactions for at least five years after completion.\n"
        "This includes wire transfers.\n"
        "2. The Bank shall train staff on these requirements at least once per year without exception.\n"
    )
    clauses = split_clauses(text)
    assert len(clauses) == 2
    assert clauses[0].text.endswith("This includes wire transfers.")


def test_sentence_fallback_without_numbering():
    text = (
        "Customer Due Diligence\n\n"
        "The bank verifies every customer. It keeps the records on file for review by auditors and supervisors at any time. "
        "Staff must escalate unusual activity to the compliance team without delay and document the escalation.\n"
    )
    clauses = split_clauses(text)
    assert len(clauses) >= 1
    assert all(text[c.start:c.end] == c.text for c in clauses)
    assert clauses[0].section == "Customer Due Diligence"


def test_heading_detection():
    assert is_heading("3. Customer Due Diligence")
    assert is_heading("ANTI-MONEY LAUNDERING POLICY")
    assert not is_heading("3.1 The Bank will verify the identity of each customer.")
    assert not is_heading('2.1 "Customer" means any person')
