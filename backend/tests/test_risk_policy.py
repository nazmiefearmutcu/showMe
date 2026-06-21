import os
import datetime
import pytest
from showme.bots.record import BotRecord, SignalEntry, ClosedTrade
from showme.bots.risk_policy import RiskPolicy, RiskConfig

@pytest.fixture(autouse=True)
def configure_test_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    # Make sure parent dirs are created
    os.makedirs(tmp_path / "state", exist_ok=True)
    os.makedirs(tmp_path / "runtime", exist_ok=True)

class DummyBroker:
    def __init__(self, positions_data=None):
        self._positions = positions_data or []
        
    async def positions(self):
        return self._positions

def test_risk_policy_kill_switch(monkeypatch):
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="paper-cred",
        exchange_id="paper",
        symbol="BTC/USDT",
        mode="live",
    )
    
    # Test active kill switch in config
    config = RiskConfig(kill_switch=True)
    RiskPolicy.save_config(config)
    
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=1.0,
        price=100.0,
        kind="entry",
    )
    assert not allowed
    assert "kill switch" in reason

    # Test active kill switch in environment
    config.kill_switch = False
    RiskPolicy.save_config(config)
    monkeypatch.setenv("SHOWME_KILL_SWITCH", "true")
    
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=1.0,
        price=100.0,
        kind="entry",
    )
    assert not allowed
    assert "kill switch" in reason

def test_risk_policy_paper_live_separation():
    # Live mode bot with a paper credential should fail
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="paper-cred",
        exchange_id="paper",
        symbol="BTC/USDT",
        mode="live",
    )
    
    RiskPolicy.save_config(RiskConfig())
    
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=1.0,
        price=100.0,
        kind="entry",
    )
    assert not allowed
    assert "paper credential" in reason

def test_risk_policy_max_position_notional():
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="live-cred",
        exchange_id="binance",
        symbol="BTC/USDT",
        mode="live",
    )
    
    config = RiskConfig(max_position_notional=1000.0)
    RiskPolicy.save_config(config)
    
    # Within limit
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=5.0,
        price=100.0,
        kind="entry",
    )
    assert allowed

    # Exceeds limit
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=15.0,
        price=100.0,
        kind="entry",
    )
    assert not allowed
    assert "exceeds max limit" in reason

def test_risk_policy_max_trades_per_day():
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="live-cred",
        exchange_id="binance",
        symbol="BTC/USDT",
        mode="live",
    )
    
    config = RiskConfig(max_trades_per_day=2)
    RiskPolicy.save_config(config)
    
    # 2 placed entries within last 24 hours
    now = datetime.datetime.now(datetime.timezone.utc)
    bot.signal_log.append(SignalEntry(bar_index=1, bar_time="", kind="entry", price=100.0, action="placed", timestamp=(now - datetime.timedelta(hours=2)).isoformat()))
    bot.signal_log.append(SignalEntry(bar_index=2, bar_time="", kind="entry", price=100.0, action="placed", timestamp=(now - datetime.timedelta(hours=1)).isoformat()))
    
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=1.0,
        price=100.0,
        kind="entry",
        now=now,
    )
    assert not allowed
    assert "daily trades count" in reason

def test_risk_policy_cooldown_after_loss():
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="live-cred",
        exchange_id="binance",
        symbol="BTC/USDT",
        mode="live",
    )
    
    config = RiskConfig(cooldown_seconds=300)
    RiskPolicy.save_config(config)
    
    now = datetime.datetime.now(datetime.timezone.utc)
    # Add a closed losing trade exit 2 minutes ago (120 seconds < 300 cooldown)
    bot.closed_trades_log.append(ClosedTrade(
        entry_timestamp="",
        exit_timestamp=(now - datetime.timedelta(seconds=120)).isoformat(),
        entry_price=100.0,
        exit_price=90.0,
        qty=1.0,
        side="long",
        pnl=-10.0,
        net_pnl=-10.0,
        bar_index_entry=1,
        bar_index_exit=2,
    ))
    
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=1.0,
        price=100.0,
        kind="entry",
        now=now,
    )
    assert not allowed
    assert "cooldown" in reason

def test_risk_policy_duplicate_order_guard():
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="live-cred",
        exchange_id="binance",
        symbol="BTC/USDT",
        mode="live",
    )
    
    RiskPolicy.save_config(RiskConfig())
    
    now = datetime.datetime.now(datetime.timezone.utc)
    bot.signal_log.append(SignalEntry(
        bar_index=1,
        bar_time="",
        kind="entry",
        price=100.0,
        action="placed",
        qty=1.0,
        timestamp=(now - datetime.timedelta(seconds=2)).isoformat(),
    ))
    
    allowed, reason = RiskPolicy.check_trade(
        bot=bot,
        active_bots=[bot],
        symbol="BTC/USDT",
        side="long",
        qty=1.0,
        price=100.0,
        kind="entry",
        now=now,
    )
    assert not allowed
    assert "duplicate order guard" in reason

@pytest.mark.asyncio
async def test_reconcile_broker():
    bot = BotRecord(
        strategy_id="strat-1",
        credential_id="live-cred",
        exchange_id="binance",
        symbol="BTC/USDT",
        mode="live",
        last_processed_event=SignalEntry(
            bar_index=1,
            bar_time="",
            kind="entry",
            price=100.0,
            action="placed",
            qty=1.0,
        ),
    )
    
    # 1. Exact match
    broker = DummyBroker(positions_data=[{"symbol": "BTC/USDT", "quantity": 1.0}])
    recon_ok, msg = await RiskPolicy.reconcile_broker(bot, broker)
    assert recon_ok
    assert msg == "reconciled"

    # 2. Mismatch
    broker_mismatch = DummyBroker(positions_data=[{"symbol": "BTC/USDT", "quantity": 0.0}])
    recon_ok_m, msg_m = await RiskPolicy.reconcile_broker(bot, broker_mismatch)
    assert not recon_ok_m
    assert "mismatch" in msg_m
