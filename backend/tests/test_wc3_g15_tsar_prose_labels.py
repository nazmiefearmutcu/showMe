"""wc3-g15 TSAR#1 follow-up: a bare two-to-four word run of Title Case prose is not a speaker.

The earlier TSAR#1 follow-up accepted any bare Title Case label after a sentence
end ("Apple Watch: Sales rose ..." became speaker "Apple Watch"), which invented
speakers from ordinary prose and fed them into the speaker rollups and the
management score. A bare label is now a speaker only when the same name already
opened a line in the transcript; a "Name, Role" label is still accepted.

Offline: calls the segmenter directly on synthetic transcript text.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.news.tsar import _segment  # noqa: E402


def test_bare_product_label_after_sentence_end_is_not_a_speaker() -> None:
    text = (
        "John Ternus, CEO: Our quarter was strong. "
        "Apple Watch: Sales rose sharply across all regions."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts
    assert any("Sales rose sharply" in u["utterance"] for u in utts), utts


def test_bare_section_label_after_sentence_end_is_not_a_speaker() -> None:
    text = (
        "John Ternus, CEO: Strong quarter overall. "
        "Management Discussion: Our team delivered solid results."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts
    assert any("delivered solid results" in u["utterance"] for u in utts), utts


def test_bare_name_turn_with_speech_opener_is_split_without_precedent() -> None:
    """Reviewer case: a bare two-word name with no line-start precedent, whose turn
    opens with a speech word, starts its own utterance. Its remarks are not
    attributed to the previous speaker, and the CFO label still splits."""
    text = (
        "Operator: Good morning and welcome. Tim Cook: Thanks everyone. "
        "Our margins improved strongly. Kevan Parekh, CFO: We expect headwinds."
    )
    utts = _segment(text)
    by_text = {u["utterance"]: u["speaker"] for u in utts}
    assert by_text.get("Good morning and welcome.") == "Operator", utts
    assert by_text.get("Thanks everyone.") == "Tim Cook", utts
    assert by_text.get("Our margins improved strongly.") == "Tim Cook", utts
    assert by_text.get("We expect headwinds.") == "Kevan Parekh, CFO", utts
    assert not any(u["speaker"] == "Operator" and "Thanks" in u["utterance"] for u in utts), utts


def test_bare_name_with_prose_body_and_no_precedent_is_not_a_speaker() -> None:
    """A bare two-word run whose body is a plain noun phrase stays in the sentence."""
    text = (
        "John Ternus, CEO: We delivered strong results. "
        "Apple Watch: Sales rose sharply across all regions."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts


def test_bare_name_that_opened_a_line_is_split_inline() -> None:
    """A name seen opening a line earlier is a real speaker when it label-splits inline."""
    text = (
        "Tim Cook: Hello.\n"
        "Operator: Good morning and welcome. Tim Cook: Thanks everyone. "
        "Our margins improved strongly."
    )
    utts = _segment(text)
    by_text = {u["utterance"]: u["speaker"] for u in utts}
    assert by_text.get("Thanks everyone.") == "Tim Cook", utts
    assert by_text.get("Our margins improved strongly.") == "Tim Cook", utts
    assert by_text.get("Good morning and welcome.") == "Operator", utts
    assert all("Tim Cook:" not in u["utterance"] for u in utts), utts


def test_name_role_label_after_sentence_end_is_still_split() -> None:
    """The 'Name, Role' form stays an accepted inline speaker without any precedent."""
    text = (
        "John Ternus, CEO: We delivered strong results. "
        "Kevan Parekh, CFO: We expect headwinds ahead."
    )
    utts = _segment(text)
    cfo = [u for u in utts if "headwinds" in u["utterance"]]
    assert cfo and cfo[0]["speaker"] == "Kevan Parekh, CFO", utts
