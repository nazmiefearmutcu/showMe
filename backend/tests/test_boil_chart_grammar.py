"""BOIL#3 residual — the declared chart grammar matches what the pane draws.

The pane (ui/src/functions/commodity-spot.tsx) draws one close-price line per
leg (CloseChart). It draws no candles, no volume histogram pane and no overlay
or compare view, so the manifest must not advertise them.

No live network: this reads the static manifest only.
"""

from __future__ import annotations

from showme.manifest.enums import ChartKind
from showme.manifest.seeds.boil_seed import boil


def test_boil_chart_kind_is_a_line_series() -> None:
    assert boil.chart_grammar is not None
    assert boil.chart_grammar.kind == ChartKind.TIME_SERIES_LINE


def test_boil_chart_panes_are_lines_only() -> None:
    panes = boil.chart_grammar.panes
    assert [p.series_kind for p in panes] == ["line"]
    assert sum(p.height_pct for p in panes) == 100


def test_boil_chart_does_not_advertise_overlay_or_compare() -> None:
    assert boil.chart_grammar.overlay_support is False
    assert boil.chart_grammar.compare_support is False
