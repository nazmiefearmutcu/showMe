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
