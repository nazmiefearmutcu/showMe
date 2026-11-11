"""MGN#3-RQ: an unmarked crypto pair is margined as spot and the assumption is stated."""
from showme.engine.services import margin_engine


def _calc(positions):
    return margin_engine.calc_account("t", positions, cfg={"accounts": {}})


def test_bare_pair_states_the_spot_assumption() -> None:
    out = _calc([{"symbol": "BTCUSDT", "asset_class": "CRYPTO", "quantity": 1.0, "last": 50000.0}])
    assert out["product_assumed_spot"] == ["BTCUSDT"]
    assert out["positions"][0]["product_assumed"] == "spot"
    assert any("margined as spot" in w and "BTCUSDT" in w for w in out["warnings"])


def test_marked_perpetual_has_no_assumption() -> None:
    out = _calc([{"symbol": "BTCUSDT", "asset_class": "CRYPTO", "contract_type": "PERPETUAL",
                  "quantity": 1.0, "last": 50000.0}])
    assert out["product_assumed_spot"] == []
    assert out["warnings"] == []
    assert "product_assumed" not in out["positions"][0]


def test_equity_has_no_assumption() -> None:
    out = _calc([{"symbol": "AAPL", "asset_class": "EQUITY", "quantity": 10.0, "last": 200.0}])
    assert out["product_assumed_spot"] == [] and out["warnings"] == []
