"""SEC 13F filings batch parser.

13F filings disclose institutional holdings (>$100M AUM) per quarter.
Filed within 45 days of quarter-end. We download per-CIK 13F-HR forms,
parse the InfoTable XML, and persist to DuckDB ``holdings`` table.

DATA PIPELINE:
    Source: https://data.sec.gov/submissions/CIK{cik}.json (filing index),
            https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/...
    Cache:  runtime/sec_13f.duckdb
    Latency: per-CIK ~1.5s (1 index request + 1 InfoTable XML fetch)
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from src.utils.throttle import throttle


_DB_PATH = Path("runtime/sec_13f.duckdb")
_NS = {"ns": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}
_NS_ALT = {"ns1": "http://www.sec.gov/edgar/thirteenffiler"}


from src.core.base_data_source import BaseDataSource, DataKind, DataRequest


class SEC13FAdapter(BaseDataSource):
    """Read-only 13F filings ingester."""
    name = "sec_13f"
    supported_kinds = (DataKind.HOLDINGS,)
    rate_limit_rps = 8.0
    requires_api_key = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.user_agent = os.environ.get("SEC_EDGAR_USER_AGENT", "ShowMe dev showme@example.com")
        self._client: httpx.AsyncClient | None = None

    async def fetch(self, request: DataRequest) -> Any:
        if request.kind != DataKind.HOLDINGS:
            return []
        sym = (request.instrument.symbol if request.instrument else None) or (
            request.symbols[0] if request.symbols else None
        )
        if not sym:
            return []
        return await self.query_holdings_by_security(issuer=sym, top_n=request.limit or 20)

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=20,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        return self._client

    @throttle(rps=8.0)
    async def _get(self, url: str) -> httpx.Response:
        client = await self._client_()
        return await client.get(url)

    async def list_filings(self, cik: str, form: str = "13F-HR", limit: int = 8) -> list[dict[str, Any]]:
        """Return last N 13F-HR filings for a CIK."""
        cik = cik.zfill(10)
        r = await self._get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        if r.status_code != 200:
            return []
        recent = (r.json().get("filings") or {}).get("recent") or {}
        forms = recent.get("form", [])
        out: list[dict[str, Any]] = []
        for i, f in enumerate(forms):
            if f != form:
                continue
            out.append({
                "form": f,
                "accession": recent["accessionNumber"][i].replace("-", ""),
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i] if "reportDate" in recent else None,
                "primary_doc": recent["primaryDocument"][i],
            })
            if len(out) >= limit:
                break
        return out

    async def fetch_holdings(self, cik: str, accession: str) -> pd.DataFrame:
        """Fetch the InfoTable XML for a given (cik, accession) and parse holdings.

        Returns DataFrame with columns:
            issuer, cusip, value_x1000, shares, share_type
        """
        cik = cik.lstrip("0") or "0"
        # 13F filings post 2013 ship an `infotable.xml` next to the index
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
        try:
            idx = await self._get(url + "index.json")
            files = (idx.json().get("directory", {}) or {}).get("item", [])
        except Exception:
            files = []
        infotable_name = None
        for f in files:
            n = f.get("name", "").lower()
            if n.endswith("infotable.xml") or n == "informationtable.xml":
                infotable_name = f["name"]
                break
        if not infotable_name:
            # Try common defaults
            for guess in ("infotable.xml", "informationtable.xml", "form13fInfoTable.xml"):
                resp = await self._get(url + guess)
                if resp.status_code == 200 and "<" in resp.text[:200]:
                    infotable_name = guess
                    break
        if not infotable_name:
            return pd.DataFrame()
        r = await self._get(url + infotable_name)
        if r.status_code != 200:
            return pd.DataFrame()
        return self._parse_infotable_xml(r.text)

    @staticmethod
    def _parse_infotable_xml(text: str) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        # Strip namespace clutter so xpath is forgiving
        clean = re.sub(r'xmlns(:\w+)?="[^"]+"', "", text)
        try:
            root = ET.fromstring(clean)
        except ET.ParseError:
            return pd.DataFrame()
        for entry in root.iter():
            tag = entry.tag.lower().split("}")[-1]
            if tag != "infotable":
                continue
            row: dict[str, Any] = {}
            for child in entry:
                ctag = child.tag.lower().split("}")[-1]
                if ctag == "nameofissuer":
                    row["issuer"] = child.text
                elif ctag == "cusip":
                    row["cusip"] = child.text
                elif ctag == "value":
                    try:
                        row["value_x1000"] = float(child.text or 0)
                    except (TypeError, ValueError):
                        row["value_x1000"] = 0
                elif ctag == "shrsorprnamt":
                    for inner in child:
                        innertag = inner.tag.lower().split("}")[-1]
                        if innertag == "sshprnamt":
                            try:
                                row["shares"] = float(inner.text or 0)
                            except (TypeError, ValueError):
                                row["shares"] = 0
                        elif innertag == "sshprnamttype":
                            row["share_type"] = inner.text
            if row:
                rows.append(row)
        return pd.DataFrame(rows)

    async def store_filing(self, cik: str, accession: str,
                            report_date: str | None = None) -> int:
        try:
            import duckdb  # type: ignore
        except Exception:
            return 0
        df = await self.fetch_holdings(cik, accession)
        if df.empty:
            return 0
        df["filer_cik"] = cik.zfill(10)
        df["accession"] = accession
        df["report_date"] = report_date or ""
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(_DB_PATH))
        con.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                filer_cik TEXT, accession TEXT, report_date TEXT,
                issuer TEXT, cusip TEXT, value_x1000 DOUBLE,
                shares DOUBLE, share_type TEXT
            )""")
        con.register("incoming", df)
        con.execute("""
            DELETE FROM holdings WHERE filer_cik = ? AND accession = ?
        """, [cik.zfill(10), accession])
        con.execute("INSERT INTO holdings SELECT * FROM incoming")
        con.close()
        return int(len(df))

    async def query_holdings_by_security(self, cusip: str | None = None,
                                          issuer: str | None = None,
                                          quarter: str | None = None,
                                          top_n: int = 20) -> pd.DataFrame:
        try:
            import duckdb  # type: ignore
        except Exception:
            return pd.DataFrame()
        if not _DB_PATH.exists():
            return pd.DataFrame()
        con = duckdb.connect(str(_DB_PATH))
        sql = "SELECT filer_cik, report_date, SUM(value_x1000)*1000 AS value_usd, SUM(shares) AS shares FROM holdings WHERE 1=1"
        params: list[Any] = []
        if cusip:
            sql += " AND cusip = ?"; params.append(cusip)
        if issuer:
            sql += " AND issuer ILIKE ?"; params.append(f"%{issuer}%")
        if quarter:
            sql += " AND report_date LIKE ?"; params.append(f"{quarter}%")
        sql += " GROUP BY filer_cik, report_date ORDER BY value_usd DESC LIMIT ?"
        params.append(top_n)
        df = con.execute(sql, params).fetchdf()
        con.close()
        return df
