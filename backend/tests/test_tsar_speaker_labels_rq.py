"""TSAR#1-RQ: a speaker label never spans a sentence end."""
from showme.engine.functions.news.tsar import _segment


def test_prose_before_a_colon_is_not_a_speaker() -> None:
    utts = _segment("Strong quarter overall. Management Discussion: Our team delivered record margins.")
    assert all(u["speaker"] != "Strong quarter overall. Management Discussion" for u in utts)
    assert all("." not in (u["speaker"] or "").rstrip(".") for u in utts)


def test_real_name_role_labels_still_split() -> None:
    utts = _segment("Tim Cook, CEO: We had a great quarter.\nKevan Parekh, CFO: Margins rose.")
    assert [u["speaker"] for u in utts] == ["Tim Cook, CEO", "Kevan Parekh, CFO"]
