"""Damodaran ERP / Country Risk Premium scraper.

Damodaran (NYU Stern) yıllık güncellenen Equity Risk Premium ve Country
Risk Premium tablolarını yayınlar. Ücretsiz, attribution gerekiyor.

Tabloyu CSV olarak indirip cache'le; günlük refresh gereksiz (yıllık).

DATA PIPELINE:
    Source: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html
            (yıllık snapshot Excel dosyası)
    Cache:  runtime/damodaran_erp.json (TTL = 30 gün)
    Latency: <2s ilk kez, sonra <50ms cache
"""

from __future__ import annotations

import asyncio
import json
import time
from showme.app_paths import runtime_path
from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest


def _cache_path():
    return runtime_path("damodaran_erp.json")


# The table is keyed by ISO-2 codes in the snapshot and by country names in a
# live workbook. Both spellings of the US map to one key (wc1-g34 WACC#3).
_US_COUNTRY_NAMES = frozenset({"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"})


def _country_key(country: str) -> str:
    key = " ".join(str(country).upper().split())
    return "US" if key in _US_COUNTRY_NAMES else key
_CACHE_TTL = 30 * 24 * 3600  # 30 gün
# Provenance label for the hard-coded table below (wc1-g34 WACC#3).
SNAPSHOT_SOURCE = "damodaran_snapshot_2025_01"
# A failed scrape serves the fallback from MEMORY only, for this long —
# a transient network error (or a missing openpyxl) must not stamp the
# January snapshot with ts=now and lock out the real scrape for 30 days.
_FALLBACK_RETRY_SECONDS = 3600  # 1 saat


# Hard-coded fallback (Jan 2025 snapshot) — kütüphane gibi kullanılır
# eğer scrape başarısız olursa. Source: NYU Stern Equity Risk Premium
# Country Risk Premium tablosu, January 2025.
_ERP_FALLBACK = {
    "_global": 4.60,           # mature market ERP (US baseline)
    "_default_emerging": 7.83,
    "US": 4.60, "USA": 4.60,
    "DE": 4.60, "GB": 4.60, "FR": 4.60, "JP": 4.60, "AU": 4.60,
    "CA": 4.60, "CH": 4.60, "NL": 4.60, "SE": 4.60, "DK": 4.60,
    "ES": 5.55, "IT": 6.07, "GR": 7.91, "PT": 5.43,
    "BR": 8.55, "MX": 6.47, "CN": 5.99, "IN": 6.65, "RU": 18.32,
    "TR": 14.12, "ZA": 9.03, "ID": 7.83, "KR": 5.07, "TW": 4.96,
    "SA": 5.95, "AE": 5.95, "AR": 24.87, "CL": 6.18, "CO": 8.80,
    "PE": 6.68, "PH": 7.23, "TH": 6.00, "VN": 9.60, "EG": 13.04,
    "NG": 14.60, "PK": 17.88, "PL": 5.95, "HU": 7.23, "CZ": 5.07,
    "RO": 7.55, "IL": 5.07, "MY": 6.18,
}


class DamodaranAdapter(BaseDataSource):
    name = "damodaran"
    supported_kinds = (DataKind.ECON_SERIES,)
    rate_limit_rps = 0.1
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None
        self._fallback_until = 0.0

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    def _cache_load(self) -> dict[str, Any] | None:
        if not _cache_path().exists():
            return None
        try:
            data = json.loads(_cache_path().read_text())
            if (time.time() - data.get("ts", 0)) < _CACHE_TTL:
                return data["payload"]
        except Exception:
            pass
        return None

    def _cache_save(self, payload: dict[str, Any]) -> None:
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps({"ts": int(time.time()), "payload": payload}))

    def _parse_workbook(self, content: bytes) -> dict[str, float] | None:
        """Parse the ctryprem.xlsx payload; ``None`` when unusable.

        Runs via ``asyncio.to_thread`` — openpyxl parsing is sync CPU/IO
        that would stall the event loop for hundreds of ms."""
        from io import BytesIO
        from openpyxl import load_workbook  # type: ignore
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        # Header row varies; we scan for a 'Country' column then 'Total Equity Risk Premium'.
        rows = list(ws.iter_rows(values_only=True))
        header_idx = None
        country_col = None
        erp_col = None
        for i, row in enumerate(rows[:20]):
            if not row:
                continue
            cells = [str(c) if c is not None else "" for c in row]
            if any("country" in c.lower() for c in cells):
                header_idx = i
                for j, c in enumerate(cells):
                    cl = c.lower()
                    if "country" in cl and country_col is None:
                        country_col = j
                    elif ("total" in cl and "equity" in cl) or "erp" in cl:
                        erp_col = j
                break
        if header_idx is None or country_col is None or erp_col is None:
            return None
        out = dict(_ERP_FALLBACK)
        for row in rows[header_idx + 1:]:
            if not row or row[country_col] is None:
                continue
            country = str(row[country_col]).strip()
            try:
                erp = float(row[erp_col]) * (100 if float(row[erp_col]) < 1 else 1)
            except (TypeError, ValueError):
                continue
            # Keep both ISO-2 and full name
            out[country] = erp
        return out

    async def _erp_table(self) -> tuple[dict[str, float], str]:
        """The ERP table and where it came from (wc1-g34 WACC#3).

        Sources: ``damodaran_cache`` (a stored scrape under its TTL),
        ``damodaran_live`` (a scrape made now) or ``damodaran_snapshot_2025_01``
        (the hard-coded January 2025 table, used when the scrape fails).
        """
        cached = self._cache_load()
        if cached is not None:
            return cached, "damodaran_cache"
        if time.time() < self._fallback_until:
            return dict(_ERP_FALLBACK), SNAPSHOT_SOURCE
        # Best-effort scrape — Damodaran's table layout varies by year.
        # We grab the 'ctryprem.xls' binary if reachable; otherwise fallback.
        try:
            client = await self._client_()
            r = await client.get(
                "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx",
                headers={"User-Agent": "ShowMe/0.2 (educational)"},
                follow_redirects=True,
            )
            if r.status_code == 200 and r.content:
                out = await asyncio.to_thread(self._parse_workbook, r.content)
                if out is not None:
                    self._cache_save(out)
                    return out, "damodaran_live"
        except Exception:
            pass
        # Fallback stays in memory with a short TTL so the real scrape is
        # retried after an hour instead of being locked out for 30 days.
        self._fallback_until = time.time() + _FALLBACK_RETRY_SECONDS
        return dict(_ERP_FALLBACK), SNAPSHOT_SOURCE

    async def country_erp(self) -> dict[str, float]:
        table, _source = await self._erp_table()
        return table

    async def fetch(self, request: DataRequest) -> Any:
        return await self.country_erp()

    async def get_erp_with_source(self, country: str) -> tuple[float, str]:
        """ERP as a decimal plus its source label.

        The country is required: a missing one is an error, never a default
        location (wc1-g34 WACC#3). A country missing from the table gets the
        mature-market (_global) value; that case is labelled
        ``..._country_unmatched`` rather than passed off as the country's own
        premium. Names match case-insensitively, and the US spellings match.
        """
        key = _country_key(country) if country else ""
        if not key:
            raise ValueError("a country is required to look up a Damodaran ERP")
        table, source = await self._erp_table()
        keys = {_country_key(name): value for name, value in table.items() if name != "_global"}
        if key in keys:
            return float(keys[key]) / 100.0, source
        return float(table.get("_global", 4.60)) / 100.0, f"{source}_country_unmatched"

    async def get_erp(self, country: str) -> float:
        erp, _source = await self.get_erp_with_source(country)
        return erp
