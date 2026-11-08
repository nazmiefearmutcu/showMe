"""ESG#5 (seed side): the ESG seed must not present an input the handler ignores
as a working control, and must not call delayed Yahoo rows live.

esg.py reads only the symbol; it never reads provider_mode. The seed keeps the
input for the existing contract, so its description must say it has no effect."""
from __future__ import annotations

from showme.manifest.seeds.esg_seed import esg


def _provider_mode_description() -> str:
    spec = next(s for s in esg.inputs if s.name == "provider_mode")
    return spec.description.lower()


def test_provider_mode_description_states_it_does_not_change_the_chain():
    text = _provider_mode_description()
    assert "no effect on the source chain" in text, text
    assert "the chain may downgrade" not in text, text


def test_methodology_does_not_present_delayed_yahoo_rows_as_live():
    text = esg.methodology.lower()
    assert "live_yfinance" not in text, text
    assert "delayed reference" in text and "not real-time" in text, text
