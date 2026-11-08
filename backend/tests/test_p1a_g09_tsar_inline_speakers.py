"""TSAR#1 regression: a speaker label inside a paragraph starts a new utterance.

When two speaker labels sit in the same block with no line break, the old
segmenter only recognised a label at the start of a line, so the second
speaker's sentence stayed under the first speaker. The CFO's guidance was then
credited to the CEO in the speaker rollups and management score.

Offline: calls the segmenter directly on synthetic transcript text.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.news.tsar import _classify_role, _segment  # noqa: E402


def test_inline_speaker_label_starts_its_own_utterance() -> None:
    text = (
        "John Ternus, CEO: We delivered strong results this quarter. "
        "Kevan Parekh, CFO: We expect headwinds in the next two quarters."
    )
    utts = _segment(text)
    cfo = [u for u in utts if "headwinds" in u["utterance"]]
    assert cfo, utts
    assert cfo[0]["speaker"] == "Kevan Parekh, CFO", cfo[0]
    assert cfo[0]["role"] == _classify_role("Kevan Parekh, CFO")
    # The CEO's own sentence stays with the CEO, and no label text leaks into it.
    ceo = [u for u in utts if "strong results" in u["utterance"]]
    assert ceo and ceo[0]["speaker"] == "John Ternus, CEO"
    assert all("CFO:" not in u["utterance"] for u in utts), utts


def test_inline_labels_across_a_paragraph_are_all_split() -> None:
    text = (
        "Operator: Our first question comes from Jane Doe, Analyst Securities. "
        "Jane Doe, Analyst Securities: Thanks. Can you comment on margins? "
        "John Ternus, CEO: Margins improved. Kevan Parekh, CFO: We see pressure ahead."
    )
    utts = _segment(text)
    by_text = {u["utterance"]: u["speaker"] for u in utts}
    margins_ceo = [s for t, s in by_text.items() if t.startswith("Margins improved")]
    pressure_cfo = [s for t, s in by_text.items() if t.startswith("We see pressure")]
    assert margins_ceo == ["John Ternus, CEO"], by_text
    assert pressure_cfo == ["Kevan Parekh, CFO"], by_text


def test_colon_inside_a_sentence_is_not_a_speaker_label() -> None:
    text = (
        "John Ternus, CEO: Revenue grew strongly. Our guidance: we raise the range."
    )
    utts = _segment(text)
    speakers = {u["speaker"] for u in utts}
    assert speakers == {"John Ternus, CEO"}, speakers


def test_prose_label_after_sentence_end_is_not_a_speaker() -> None:
    """A single-word prose label such as 'Guidance:' or 'Note:' is not a speaker."""
    text = (
        "John Ternus, CEO: We delivered strong results this quarter. "
        "Guidance: we raise the range for the year."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts
    assert any("raise the range" in u["utterance"] for u in utts), utts
    assert all(u["speaker"] == "John Ternus, CEO" for u in utts), utts


def test_note_label_after_sentence_end_is_not_a_speaker() -> None:
    text = (
        "John Ternus, CEO: We delivered strong results. "
        "Note: this excludes FX effects."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts
    assert any("excludes FX effects" in u["utterance"] for u in utts), utts


def test_known_single_word_speaker_inline_is_still_split() -> None:
    """'Operator' opened a line earlier, so an inline 'Operator:' label is a real speaker."""
    text = (
        "Operator: Welcome to the call. "
        "John Ternus, CEO: Thanks. Operator: Our next question comes from Jane Doe."
    )
    utts = _segment(text)
    by_text = {u["utterance"]: u["speaker"] for u in utts}
    assert by_text.get("Our next question comes from Jane Doe.") == "Operator", by_text


def test_two_word_name_label_after_sentence_end_is_split() -> None:
    """TSAR#1 follow-up: a two-word speaker name with no comma, inline after a
    sentence end, starts its own utterance (the reviewer's transcript case)."""
    text = (
        "Operator: Good morning and welcome. Tim Cook: Thanks everyone. "
        "Our margins improved strongly. Kevan Parekh, CFO: We expect headwinds next quarter."
    )
    utts = _segment(text)
    by_text = {u["utterance"]: u["speaker"] for u in utts}
    assert by_text.get("Thanks everyone.") == "Tim Cook", utts
    assert by_text.get("Our margins improved strongly.") == "Tim Cook", utts
    assert by_text.get("We expect headwinds next quarter.") == "Kevan Parekh, CFO", utts
    assert by_text.get("Good morning and welcome.") == "Operator", utts
    assert all("Tim Cook:" not in u["utterance"] for u in utts), utts
    assert all("CFO:" not in u["utterance"] for u in utts), utts


def test_two_word_inline_label_with_figure_body_is_not_a_speaker() -> None:
    """A metric label followed by a figure is prose, not a speaker turn."""
    text = (
        "John Ternus, CEO: We delivered strong results. "
        "Free Cash Flow: $2.1 billion this quarter."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts
    assert any("$2.1 billion" in u["utterance"] for u in utts), utts


def test_two_word_metric_heading_is_not_a_speaker() -> None:
    """Metric and section heads with a stoplisted word stay in the sentence."""
    text = (
        "John Ternus, CEO: We delivered strong results. "
        "Gross Margin: Expanded across all regions."
    )
    utts = _segment(text)
    assert {u["speaker"] for u in utts} == {"John Ternus, CEO"}, utts
    assert any("Expanded across all regions" in u["utterance"] for u in utts), utts
