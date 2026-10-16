from backend.tools.quote import clip_words, normalize, quote_in_text, quote_matcher

TEXT = "3.2 Customer identification records may be verified within 90 days after the account is opened."


def test_exact_match():
    s, e, score = quote_matcher("verified within 90 days", TEXT)
    assert TEXT[s:e] == "verified within 90 days" and score == 100


def test_normalized_match_maps_back_to_original_offsets():
    text = "The Bank’s  records   “shall” be kept\nfor five years."
    s, e, score = quote_matcher('bank\'s records "shall" be kept for five years', text)
    assert score == 99
    assert text[s:e] == "Bank’s  records   “shall” be kept\nfor five years"


def test_fuzzy_match_tolerates_small_differences():
    s, e, score = quote_matcher("records may be verfied within 90 day after the account", TEXT)
    assert s >= 0 and score >= 85
    assert "verified within 90 days" in TEXT[s:e]


def test_not_found():
    s, e, score = quote_matcher("capital adequacy ratio of twelve percent", TEXT)
    assert (s, e) == (-1, -1)


def test_quote_in_text_and_helpers():
    assert quote_in_text("“verified within 90 days”", TEXT)
    assert not quote_in_text("verified within 30 days of opening", TEXT, threshold=95)
    assert normalize("A —  B") == "a - b"
    assert clip_words("one two three four", 2) == "one two"
