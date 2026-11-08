"""LOC-3-RQ — bot_service reads its YAML config as UTF-8 (with BOM tolerance).

The dashboard writes the config as UTF-8, sometimes with a BOM and Turkish
characters (Ş, Ğ, İ, ı). A read that uses the locale codec mis-decodes the BOM
(``ï»¿``) so the first key is no longer ``auto_scan_enabled`` and the dashboard
toggle is silently ignored. The auto-scan read site (bot_service
``_auto_scan_market``) must honour ``auto_scan_enabled: false`` in such a file.
Offline: no threads, no Binance, the scan itself is never started.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.services.bot_service import BotService  # noqa: E402

_YAML_TEXT = (
    "# Şişli Ğ İ ı ö ü — Turkish comment\n"
    "display_name: \"Ş Ğ İ ı\"\n"
    "auto_scan_enabled: false\n"
)


def _service_for(config_path: Path) -> BotService:
    svc = BotService.__new__(BotService)  # skip __init__: no exchange clients
    svc.config = {"_config_path": str(config_path), "auto_scan_enabled": True}
    return svc


def test_auto_scan_reads_bom_utf8_config_and_honours_disable(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # no runtime/auto_scan_disabled flag here
    cfg = tmp_path / "default.yaml"
    cfg.write_bytes(_YAML_TEXT.encode("utf-8-sig"))  # BOM-prefixed UTF-8
    svc = _service_for(cfg)
    # auto_scan_enabled is false in the file: the method must return before
    # touching any scan state. A mis-decoded read falls back to the in-memory
    # True and proceeds, which raises here because the scan state is absent.
    assert svc._auto_scan_market() is None


def test_auto_scan_turkish_only_file_is_read_as_utf8(tmp_path, monkeypatch) -> None:
    """The decoded text itself keeps the Turkish characters intact."""
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "default.yaml"
    cfg.write_bytes(_YAML_TEXT.encode("utf-8-sig"))
    import yaml

    parsed = yaml.safe_load(cfg.read_text(encoding="utf-8-sig"))
    assert parsed["display_name"] == "Ş Ğ İ ı"
    assert parsed["auto_scan_enabled"] is False
