"""CME FedWatch — Fed funds futures-implied rate move probabilities.

Best-effort scrape of the public CME endpoint.
"""

from __future__ import annotations

from typing import Any

import httpx

from showme.engine.core.base_data_source import BaseDataSource, DataKind, DataRequest


class CMEFedWatchAdapter(BaseDataSource):
    name = "cme_fedwatch"
    supported_kinds = (DataKind.OTHER,)
    rate_limit_rps = 0.2

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.base_url = (config or {}).get(
            "base_url",
            "https://www.cmegroup.com/CmeWS/mvc/CompoundProbability/MeetingProbability",
        )
        self._client: httpx.AsyncClient | None = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self._client

    async def probabilities(self) -> dict[str, Any]:
        """Pull FOMC meeting probabilities from CME's public JSON endpoint.

        Falls back to a curated alternate URL if the primary is rate-limited.
        Output: list of {meeting_date: ..., probabilities: {rate_range: pct}}
        """
        client = await self._client_()
        urls = [
            self.base_url,
            "https://www.cmegroup.com/CmeWS/mvc/MarketData/marketStrip?id=200145",  # FF futures
        ]
        for url in urls:
            try:
                r = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (ShowMe/0.2)",
                    "Accept": "application/json",
                })
                if r.status_code == 200:
                    js = r.json()
                    return self._normalize(js)
            except Exception:
                continue
        return {}

    @staticmethod
    def _normalize(payload: Any) -> dict[str, Any]:
        """Map raw CME payload → normalized {meetings: [{date, ranges: {bin: pct}}]}.

        CME's structure varies; we keep both raw and a best-effort rollup.
        """
        out: dict[str, Any] = {"raw": payload, "meetings": []}
        if isinstance(payload, dict):
            # Pattern 1: nested 'meetingProbability' array
            mps = payload.get("meetingProbability") or payload.get("meetings") or []
            for mp in mps if isinstance(mps, list) else []:
                meeting = {"date": mp.get("meetingDate") or mp.get("date"),
                            "ranges": {}}
                for prob in (mp.get("probabilities") or mp.get("data") or []):
                    rng = prob.get("range") or prob.get("rateRange") or prob.get("bin")
                    pct = prob.get("probability") or prob.get("pct") or prob.get("value")
                    if rng is not None and pct is not None:
                        try:
                            meeting["ranges"][str(rng)] = float(pct)
                        except (TypeError, ValueError):
                            continue
                if meeting["date"]:
                    out["meetings"].append(meeting)
        return out

    async def fetch(self, request: DataRequest) -> Any:
        return await self.probabilities()
