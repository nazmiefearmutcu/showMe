# showMe Provider Matrix

Audit date: 2026-05-24

All providers are instantiated in `backend/showme/engine/services/function_factory.py` and exposed as attributes on `FunctionDeps`. Functions consume them via `self.deps.<name>`. Files marked "wrapped by OhlcvLongestHistoryWrapper" are wrapped in the factory so OHLCV requests run through the cross-source longest-history race.

| Provider | Where used (file paths) | Auth required | Rate limits | Current mode coverage | Notes |
|----------|-------------------------|---------------|-------------|------------------------|-------|
| `yfinance` | backend/showme/engine/data_sources/equity/yfinance_adapter.py — consumed by 47 functions incl. GP/HP alias, EQS, FA, DES, WACC, EE, BETA, BTFW, MGN, PORT, PCAS, CORR, OMON, OVME, GEX, BLAK, RPAR, BMTX, BTUNE, ML SIG, RV, ESG, HDS, FXH, FRD, FXFC, FXIP, REGM, EVTS, CACT, FORM4, MOST, WEI, MAP, SECT, ICX, MICRO, FRH, BOIL, BGAS, NGAS, GLCO, MIS scanner | None (curl_cffi reverse) | yfinance throttles ~2 req/s; fragile | OHLCV, QUOTE, REFDATA, HOLDINGS | wrapped by OhlcvLongestHistoryWrapper |
| `finnhub` | backend/showme/engine/data_sources/equity/finnhub_adapter.py — consumed by EE, ERV, ANR, RV, CN, TOP | API key (`FINNHUB_API_KEY`) | 60 req/min free | recommendations, peers, earnings | optional — degrades if key absent |
| `alphavantage` | backend/showme/engine/data_sources/equity/alphavantage_adapter.py — wired but no function directly consumes it today | API key | 5 req/min free | EQUITY OHLCV fallback | wrapped by longest-history; INTENT-UNCLEAR (registered but unused) |
| `polygon` | backend/showme/engine/data_sources/equity/polygon_adapter.py — wired; unused by current function code | API key | 5 req/min free / paid | EQUITY OHLCV fallback | wrapped by longest-history; unused |
| `eodhd` | backend/showme/engine/data_sources/equity/eodhd_adapter.py — wired; unused | API key | per-plan | EQUITY OHLCV/fundamentals | wrapped; unused |
| `stooq` | backend/showme/engine/data_sources/equity/stooq_adapter.py — wired; unused by code today | None | none documented | EQUITY OHLCV backup | unused |
| `sec_edgar` | backend/showme/engine/data_sources/equity/sec_edgar_adapter.py — consumed by FA, CACT, FORM4, SPLC, PIB | None (User-Agent header required) | 10 req/s SEC fair-use | filings, fundamentals, CIK lookup | present and used |
| `sec_13f` | backend/showme/engine/data_sources/equity/sec_13f_adapter.py — consumed by HFS | None | SEC fair-use | 13F holdings | present |
| `sec_efts` | backend/showme/engine/data_sources/equity/sec_efts_adapter.py — consumed by FTS | None | SEC fair-use | full-text search of filings | present |
| `seekingalpha` | backend/showme/engine/data_sources/equity/seekingalpha_adapter.py — consumed by TRAN | None | scrape-based, very fragile | transcripts | scrape |
| `finra` | backend/showme/engine/data_sources/equity/finra_adapter.py — consumed by DPF, DARK | None | weekly ATS reports | dark pool ATS | present |
| `coingecko` | backend/showme/engine/data_sources/crypto/coingecko_adapter.py — consumed by GP/HP alias for crypto, DES crypto rail | None (key optional) | 30 req/min free | CRYPTO OHLCV, REFDATA, top tokens | wrapped |
| `cryptocompare` | backend/showme/engine/data_sources/crypto/cryptocompare_adapter.py — wired; rarely used | None (key optional) | 100k req/month free | CRYPTO OHLCV fallback | wrapped |
| `ccxt_failover` | backend/showme/engine/data_sources/crypto/ccxt_failover_adapter.py — consumed by GP/HP alias (Binance via ccxt), DES, MIS scanner, SCAN | None for public endpoints | exchange-specific | CRYPTO OHLCV + QUOTE | wrapped; uses Binance public ccxt by default |
| `fred` | backend/showme/engine/data_sources/macro/fred_adapter.py — consumed by WACC, OVME, ECST, REGM, WB, CRVF, GC3D, SRSK, TLH (DCF), YAS | API key (`FRED_API_KEY`) | 120 req/min free | macro time series, yield curve | PRESENT |
| `worldbank` | backend/showme/engine/data_sources/macro/worldbank_adapter.py — consumed by ECST | None | very high | macro indicators (USA + others) | present |
| `imf` | backend/showme/engine/data_sources/macro/imf_adapter.py — consumed by ECFC | None | low rate | macro forecasts | present |
| `oecd` | backend/showme/engine/data_sources/macro/oecd_adapter.py — consumed by ECFC | None | low rate | macro forecasts | present |
| `tradingeconomics` | backend/showme/engine/data_sources/macro/tradingeconomics_adapter.py — consumed by ECO, GMM | API key (free tier OK) | 100 req/day free | economic calendar | present |
| `cme_fedwatch` | backend/showme/engine/data_sources/macro/cme_fedwatch_adapter.py — declared in deps, NOT consumed by WIRP today | None (CME public XML) | none documented | FedWatch probabilities | WIRP gap — adapter present, pane uses reference table |
| `damodaran` | backend/showme/engine/data_sources/macro/damodaran_adapter.py — consumed by WACC (ERP) | None | yearly static spreadsheet | ERP, country risk premium | present |
| `ecb` | backend/showme/engine/data_sources/fx/ecb_adapter.py — consumed by FRD, FXIP | None | ECB SDMX | FX reference rates | present |
| `exchangerate_host` | backend/showme/engine/data_sources/fx/exchangerate_host_adapter.py — consumed by FX `_funcs` | None | 100 req/min | FX latest rates | present |
| `eia` | backend/showme/engine/data_sources/commodity/eia_adapter.py — consumed by BOIL, BGAS, NGAS | API key (free) | 5000 req/hour | crude/natgas inventories | present |
| `ustreasury` | backend/showme/engine/data_sources/bond/ustreasury_adapter.py — declared; unused by current code | None | fiscaldata public API | US Treasury yields | declared but no function consumes it today |
| `treasury_auctions` | backend/showme/engine/data_sources/bond/treasury_auctions_adapter.py — consumed by TAUC (TreasuryDirect Fiscal API) | None | fiscaldata public API | auction calendar | THIS IS the TreasuryDirect coverage |
| `gdelt` | backend/showme/engine/data_sources/news/gdelt_adapter.py — consumed by NI, CN (deep mode), TOP | None (GDELT 2.0 Open) | rate-limited per IP | global news graph | present |
| `rss` | backend/showme/engine/data_sources/news/rss_adapter.py — consumed by NI, CN, NSE, NALRT, INSTANT | None | per-feed | RSS / Atom | present |
| `finnhub_news` | backend/showme/engine/data_sources/news/finnhub_news_adapter.py — consumed by CN, TOP | API key (`FINNHUB_API_KEY`) | 60 req/min | news headlines | present |
| `reddit` | backend/showme/engine/data_sources/alt/reddit_adapter.py — consumed by SOSC | None (read JSON) | per-IP | subreddit posts | present |
| `stocktwits` | backend/showme/engine/data_sources/alt/stocktwits_adapter.py — consumed by SOSC | None | per-IP | symbol stream | present |
| `openweather` | backend/showme/engine/data_sources/alt/openweathermap_adapter.py — consumed by WETR, BOIL/BGAS (HDD/CDD) | API key (free tier) | 60 req/min free | weather/climate | present |
| `sentinelhub` | backend/showme/engine/data_sources/alt/sentinelhub_adapter.py — consumed by SAT | API key (paid) | per-plan | satellite imagery | present |
| `opensky` | backend/showme/engine/data_sources/alt/opensky_adapter.py — consumed by FLY | None | 100 req/day anon | flight data | present |
| `glassnode` | backend/showme/engine/data_sources/alt/glassnode_adapter.py — declared; unused | API key (paid) | per-plan | on-chain metrics | declared, no function wired |
| `etherscan` | backend/showme/engine/data_sources/alt/etherscan_adapter.py — consumed by ONCH (ETH chain) | API key (free tier OK) | 5 req/s free | Ethereum chain explorer | present |
| `mempool` | backend/showme/engine/data_sources/alt/mempool_adapter.py — consumed by ONCH (BTC chain) | None | mempool.space public | Bitcoin mempool/fees | present |
| `polymarket` | backend/showme/engine/data_sources/alt/polymarket_adapter.py — consumed by POLY | None | per-IP | prediction markets | present |
| `notion` | backend/showme/engine/data_sources/alt/notion_adapter.py — declared; unused by user-facing function code today | OAuth | per-workspace | Notion blocks | declared, used by assistant flows only |
| `granola` | backend/showme/engine/data_sources/alt/granola_adapter.py — consumed by MEET | API key | per-account | meeting transcripts | present |
| `openfigi` | backend/showme/engine/data_sources/reference/openfigi_adapter.py — consumed by ISIN, BQL, SymbolRegistry (every function that resolves a symbol) | None for low volume; key for ≥25/min | 25 req/min free | symbology resolution | PRESENT and pervasive |
| `binance-ws` (StreamHub) | backend/showme/streams.py — consumed by `useLiveQuote` (every chart pane) via `/api/quote/{symbol}` + SSE | None for public ticker stream | none documented; sidecar caps | live crypto ticks | PRESENT (BinanceHybridSource = ws + REST fallback) |
| `treasury_direct` (TreasuryDirect Fiscal API) | backend/showme/providers/treasury_direct.py + treasury_auctions_adapter.py — consumed by TAUC | None | fiscaldata public | auction calendar + results | PRESENT |
| `finbert` (ProsusAI/finbert via transformers) | backend/showme/engine/services/sentiment.py — declared, NOT consumed by any TOP/NI/CN/INSTANT today | None (HuggingFace cache) | CPU 2-5s warmup | finance sentiment | PRESENT but UNWIRED |
| `cardiffnlp/twitter-roberta-base-sentiment` | spec asks; codebase uses showMe's own fine-tune `showme_x_v1` at backend/showme/x_analysis.py + bundled data/x_model/showme_x_v1 | None (bundled local) | CPU ~1-2s per batch | sentiment / emotion / topic | SUBSTITUTED — bundled `showme_x_v1` (RoBERTa-base + 3 heads) covers the same use case but is NOT cardiffnlp. Spec mismatch. |
| `whisper` (openai-whisper / faster-whisper / openai API) | backend/showme/engine/services/transcription.py — declared, NOT consumed by INSTANT / TRAN / TRQA today | None for local; key for openai fallback | local CPU 1-3× realtime | audio transcription | PRESENT but UNWIRED |

---

## MISSING (or present-but-unwired) vs spec

| Spec-required provider | Status | Location if present |
|------------------------|--------|---------------------|
| SEC EDGAR | **Present (wired)** | `backend/showme/engine/data_sources/equity/sec_edgar_adapter.py` |
| FRED | **Present (wired)** | `backend/showme/engine/data_sources/macro/fred_adapter.py` |
| TreasuryDirect | **Present (wired)** | `backend/showme/providers/treasury_direct.py` + `backend/showme/engine/data_sources/bond/treasury_auctions_adapter.py` (consumed by TAUC) |
| OpenFIGI | **Present (wired)** | `backend/showme/engine/data_sources/reference/openfigi_adapter.py` |
| GDELT | **Present (wired)** | `backend/showme/engine/data_sources/news/gdelt_adapter.py` |
| Binance official WS | **Present (wired)** | `backend/showme/streams.py` (`BinanceWebSocketSource` / `BinanceHybridSource`) |
| FinBERT | **Present but UNWIRED in user-facing panes** | `backend/showme/engine/services/sentiment.py` (loads `ProsusAI/finbert`) — no TOP/NI/CN/INSTANT consumer |
| CardiffNLP Twitter RoBERTa | **MISSING (substituted with showMe's own `showme_x_v1`)** | `backend/showme/x_analysis.py` loads bundled `data/x_model/showme_x_v1` instead |
| Whisper large-v3 | **Present but UNWIRED, and "base" model by default** | `backend/showme/engine/services/transcription.py` uses `model_name = "base"` default; no AV/TRAN/INSTANT consumer |

Additional gaps surfaced by the audit (not in the spec but worth flagging for the rebuild):

| Provider | Status | Notes |
|----------|--------|-------|
| `ustreasury` (Fiscal Service yields) | DECLARED but no function consumes it | TAUC uses the auctions adapter only; no pane consumes USTreasury yields directly. |
| `alphavantage`, `polygon`, `eodhd`, `stooq` | DECLARED but no production function consumes them | They're chain candidates only; current code prefers yfinance for OHLCV. |
| `cme_fedwatch` | DECLARED, consumed by ECO/GMM, NOT consumed by WIRP | WIRP shows acknowledged "reference rate probability table" — wiring is the gap. |
| `glassnode` | DECLARED, NO consumer | Required for any deep BTC on-chain pane the rebuild adds. |
| `notion` | DECLARED, consumed only by assistant/agent helpers, not by a user-pane | OK if intentional. |
