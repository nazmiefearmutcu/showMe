# showMe Function Inventory

Audit date: 2026-05-24
Total codes in catalogue: **141** (union of `DESIGN_BASIC_CODES`, `DESIGN_PRO_CODES`, native registry, template mock-data, and engine `FunctionRegistry`).

Codes whose UI resolves to `FunctionStub` render via `ui/src/panes/function_stub/index.tsx` (calls `/api/fn/{code}`, displays generic JSON tree + a small set of stock controls).
Codes whose UI resolves to `TemplateRenderer` overlay a sidecar payload onto a hard-coded Design mock from `ui/src/templates/mock-data.ts`.
"design-export" tier was collapsed to "stub" in Workspace.tsx on 2026-05-23 (per QA-2026-05-23) but the data list is still consumed by `pane-completeness.ts`.

Provider keys:
- `yfinance`, `coingecko`, `cryptocompare`, `ccxt_failover` — OHLCV/quote
- `fred`, `worldbank`, `imf`, `oecd`, `tradingeconomics`, `cme_fedwatch`, `damodaran` — macro
- `ecb`, `exchangerate_host` — FX
- `eia`, `ustreasury`, `treasury_auctions` (TreasuryDirect Fiscal API) — commodity / bond
- `rss`, `gdelt`, `finnhub_news` — news
- `sec_edgar`, `sec_13f`, `sec_efts`, `finra` — equity disclosures
- `finnhub`, `polygon`, `alphavantage`, `eodhd`, `stooq`, `seekingalpha` — equity
- `openfigi` — reference symbology
- `reddit`, `stocktwits`, `openweathermap`, `sentinelhub`, `opensky`, `glassnode`, `etherscan`, `mempool`, `polymarket`, `notion`, `granola` — alt/onchain
- `binance-ws` — sidecar `StreamHub` (BinanceHybridSource ws→rest fallback) for live ticks
- `internal-mock` — `ui/src/templates/mock-data.ts` static rows
- `formula-only` — Black-Scholes / Heston / covered-interest-parity computed in-process
- `none` — engine returns deterministic reference/template payload without any external call

---

## Portfolio

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| PORT | ui/src/functions/PORT.tsx | bespoke | engine/functions/portfolio/port.py + portfolio_aggregate.py | yfinance, ccxt (broker), portfolio_state | yes | n/a (table only) | Multi-credential aggregation; CRITICAL code |
| ACCT | (FunctionStub) | function-stub | engine/functions/portfolio/acct.py | yfinance, portfolio_state | no (JSON only) | no | Mock template exists |
| MGN | (FunctionStub) | function-stub | engine/functions/portfolio/mgn.py | yfinance, portfolio_state | no | no | Mock template exists |
| LOTS | (FunctionStub) | function-stub | engine/functions/portfolio/lots.py | local_tax_lot_ledger | no | no | No external provider |
| TLH | (FunctionStub) | function-stub | engine/functions/portfolio/tlh.py | yfinance, portfolio_state | no | no | Mostly model fallback |
| PCAS | (FunctionStub) | function-stub | engine/functions/portfolio/pcas.py | yfinance, portfolio_state | no | no | Mock template exists |
| PVAR | (FunctionStub) | function-stub | engine/functions/portfolio/pvar.py | yfinance (when live), portfolio_state | no | no | Mostly risk_model |
| PFA | (FunctionStub) | function-stub | engine/functions/portfolio/pfa.py | brinson_model (internal) | no | no | INTENT-UNCLEAR (no upstream feed) |
| REBA | (FunctionStub) | function-stub | engine/functions/portfolio/reba.py | yfinance, portfolio_state | no | no | rebalance_model fallback |
| RPAR | (FunctionStub) | function-stub | engine/functions/portfolio/rpar.py | yfinance | no | no | Risk-parity model |
| PORT_OPT | (FunctionStub) | function-stub | engine/functions/portfolio/port_opt.py | yfinance | no | no | Mock template exists |
| PORT_WHATIF | (FunctionStub) | function-stub | engine/functions/portfolio/_more.py | yfinance, portfolio_state | no | no | Hypothetical position run |
| STRS | (FunctionStub) | function-stub | engine/functions/portfolio/strs.py | yfinance, stress_scenarios | no | no | Mock template exists |
| GREEKS | (FunctionStub) | function-stub | engine/functions/portfolio/greeks.py | none (formula-only) | no | no | Black-Scholes greeks |
| BLAK | (FunctionStub) | function-stub | engine/functions/portfolio/blak.py | yfinance | no | no | Black-Litterman; mock exists |
| BTFW | (FunctionStub) | function-stub | engine/functions/portfolio/btfw.py | yfinance | no | no | Backtest walk-forward; mock exists |
| BTUNE | (FunctionStub) | function-stub | engine/functions/portfolio/btune.py | yfinance | no | no | Tuning; mock exists |
| BMTX | (FunctionStub) | function-stub | engine/functions/portfolio/bmtx.py | yfinance | no | no | Backtest matrix; mock exists |
| MLSIG | (FunctionStub) | function-stub | engine/functions/portfolio/mlsig.py | yfinance, ml_signal_model | yes (horizon) | no | Custom MLSignalControls in stub |
| CORR | ui/src/functions/CORR.tsx | bespoke | engine/functions/portfolio/corr.py | yfinance | yes | partial (heat-grid via HeatCell, OK) | Full Pearson/Spearman/downside matrix |
| PSC | (FunctionStub) | function-stub | engine/functions/portfolio/psc.py | position_sizing_model | no | no | Internal model |
| BOT | ui/src/functions/BOT.tsx | bespoke | server_routes/bots.py + engine/services/bot_service.py | yfinance, ccxt (live broker) | yes | n/a | Sub-system D user surface |
| BOTS | ui/src/functions/BOTS.tsx | bespoke | server_routes/bots.py | bot_service | yes | n/a | Supervisor pane |
| PERF | ui/src/functions/PERF.tsx | bespoke | server_routes/bots.py | bot_service (signal_log) | yes | yes (custom SVG equity curve) | Cumulative bot performance |
| STRA | ui/src/functions/STRA.tsx | bespoke | server_routes/strategies.py | strategy compute engine | yes | n/a | Sub-system E editor |
| BDA | ui/src/functions/BDA.tsx | bespoke | server_routes/assistant.py | rule-based NL parser | yes | n/a | Sub-system J |
| TMPL | ui/src/functions/TMPL.tsx | bespoke | server_routes/templates.py | YAML catalog (G subsystem) | yes | n/a | Curated strategy templates |
| INDX | ui/src/functions/INDX.tsx | bespoke | server_routes/indicators.py | hand-curated indicator catalog | yes | n/a | Sub-system F depot |
| CONN | ui/src/functions/CONN.tsx | bespoke | server_routes/exchange.py + broker.py | ccxt (112 exchange catalog) | yes | n/a | Sub-system A connect/test |
| AGENT | ui/src/functions/AGENT.tsx | bespoke | server_routes/agent.py + _agent_runtime.py | every fn registry probe | yes | n/a | Ranks functions for a symbol |

## Trade/Execution

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| EMSX | ui/src/functions/EMSX.tsx | bespoke | engine/functions/trade/_funcs.py (EMSXFunction) | order_history, ccxt broker | yes | n/a | Order management; not a true execution gateway |
| TSOX | ui/src/functions/TSOX.tsx | bespoke | engine/functions/trade/_funcs.py | TCA service | yes | n/a | Time-Sliced Order eXecution |
| TCA | (FunctionStub) | function-stub | engine/functions/trade/tca.py | execution_log | no | no | Mock template exists |
| EXEC | (FunctionStub) | function-stub | engine/functions/trade/exec.py | exec_monitor | no | no | Execution monitor |
| AIM | (FunctionStub) | function-stub | engine/functions/trade/_funcs.py | AIM service stub | no | no | Mock template exists |
| FXGO | (FunctionStub) | function-stub | engine/functions/trade/_funcs.py | none | no | no | FX desk reference only; INTENT-UNCLEAR |
| BBGT | (FunctionStub) | function-stub | engine/functions/trade/_funcs.py | none | no | no | INTENT-UNCLEAR |
| GRAB | (FunctionStub) | function-stub | engine/functions/misc/_extras.py | local_capture_plan | no | no | Capture/clipping helper |
| OrderTicket | ui/src/functions/OrderTicket.tsx | bespoke (not a fn code) | server_routes/broker.py | ccxt broker | yes | n/a | Used inside PORT/BOT modals |

## API / Dev

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| BQL | (FunctionStub) | function-stub | engine/functions/api/bql.py | OpenFIGI + yfinance (limited) | no (JSON only) | no | Mock exists; BQL query DSL stub |
| BQUANT | (FunctionStub) | function-stub | engine/functions/api/bquant.py | none | no | no | Mock template; INTENT-UNCLEAR |
| DAPI | (FunctionStub) | function-stub | engine/functions/api/dapi.py | yfinance, fred | no | no | Mock template exists |
| FLDS | (FunctionStub) | function-stub | engine/functions/api/flds.py | none | no | no | Field dictionary |
| ISIN | (FunctionStub) | function-stub | engine/functions/api/isin.py | openfigi | no | no | ISIN lookup |
| LANG | (FunctionStub) | function-stub | engine/functions/misc/_extras.py | showme_i18n_registry | no | no | Locale picker (writes runtime/lang.txt) |
| KEYB | (FunctionStub) | function-stub | n/a | none | no | no | Keyboard reference (no backend) — pane not implemented |
| CATALOG | (FunctionStub) | function-stub | n/a | none | no | no | INTENT-UNCLEAR |

## Bonds / Rates

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| WB | ui/src/functions/WB.tsx | bespoke | engine/functions/bond/wb.py | fred | yes | n/a (KPI strip + table) | World Bond rates monitor |
| WIRP | ui/src/functions/WIRP.tsx | bespoke | engine/functions/macro/wirp.py | reference_rate_probability_table | yes (bank picker) | n/a (table+cards) | Honest "reference" pill — NO live FedWatch adapter wired |
| CRVF | (FunctionStub) | function-stub | engine/functions/bond/crvf.py | fred | no | no | Curve fitting |
| GC3D | (FunctionStub) | function-stub | engine/functions/bond/gc3d.py | fred | no | no | 3D curve cube |
| SRSK | (FunctionStub) | function-stub | engine/functions/bond/srsk.py | fred | no | no | Sovereign spread risk |
| TAUC | (FunctionStub) | function-stub | engine/functions/bond/tauc.py | treasury_auctions (TreasuryDirect) | no | no | Auction calendar |
| YAS | (FunctionStub) | function-stub | engine/functions/bond/yas.py | fred | no | no | Mock template exists |
| CRPR | (FunctionStub) | function-stub | engine/functions/bond/_stubs.py | none | no | no | Credit pricer — INTENT-UNCLEAR |
| DDIS | (FunctionStub) | function-stub | engine/functions/bond/_stubs.py | none | no | no | INTENT-UNCLEAR |
| DEBT | (FunctionStub) | function-stub | engine/functions/bond/_stubs.py | none | no | no | INTENT-UNCLEAR |
| ALLQ | (FunctionStub) | function-stub | engine/functions/bond/_stubs.py | none | no | no | All-quote consolidated |

## Charts / Tech

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| GP | ui/src/functions/GP.tsx | bespoke | server.py `_execute_price_history_alias` | yfinance, ccxt_failover, coingecko | yes | yes (lightweight-charts candles) | CRITICAL |
| HP | ui/src/functions/HP.tsx | bespoke | server.py `_execute_price_history_alias` | yfinance, ccxt_failover, coingecko | yes | yes (lightweight-charts candles) | CRITICAL |
| TECH | (FunctionStub) | function-stub | engine/functions/chart/tech.py | yfinance | no | no | Technical indicator dump; mock exists |
| BTMM | ui/src/functions/BTMM.tsx | bespoke | engine/functions/macro/btmm.py | fred (when wired) | yes | yes (lightweight-charts) | Market monitor |
| GLCO | ui/src/functions/GLCO.tsx | bespoke | engine/functions/commodity/_funcs.py | yfinance | yes | yes (lightweight-charts) | Gold/commodity overlay |
| WCRS | ui/src/functions/WCRS.tsx | bespoke | engine/functions/fx/_funcs.py | yfinance, ecb | yes | yes (lightweight-charts) | World cross-rate strength |
| GEX | ui/src/functions/GEX.tsx | bespoke | engine/functions/derivative/gex.py | yfinance (options) + Black-Scholes formula | yes | yes (BAR chart of gamma) | Real gamma bars |

## Comms / People

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| MEET | (FunctionStub) | function-stub | engine/functions/comm/meet.py | granola | no | no | Mock template exists |
| PEOP | (FunctionStub) | function-stub | engine/functions/comm/peop.py | none | no | no | Mock template exists |
| ASK | ui/src/functions/ASK.tsx | bespoke | server_routes/ask.py | function probes + LLM | yes | n/a | Research assistant |
| BRIEF | (FunctionStub) | function-stub | engine/functions/news/brief.py | watchlist_brief_builder (internal) | no | no | Mock template exists |
| READ | (FunctionStub) | function-stub | engine/functions/news/read.py | watchlist_cache | no | no | Mock template exists |
| TLDR | (FunctionStub) | function-stub | engine/functions/news/tldr.py | none (deterministic) | no | no | Headline summariser |

## Commodities

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| BOIL | (FunctionStub) | function-stub | engine/functions/commodity/_funcs.py | yfinance, eia | no | no | Oil/crude monitor; mock exists |
| BGAS | (FunctionStub) | function-stub | engine/functions/commodity/_funcs.py | yfinance, eia | no | no | Natural gas; mock exists |
| NGAS | (FunctionStub) | function-stub | engine/functions/commodity/_funcs.py | yfinance, eia | no | no | NatGas variant |
| CPF | (FunctionStub) | function-stub | engine/functions/commodity/_funcs.py | none | no | no | INTENT-UNCLEAR |
| WETR | ui/src/functions/WETR.tsx | bespoke | engine/functions/commodity/_funcs.py | openweathermap | yes | n/a (table) | Weather monitor (commodity context) |

## Derivatives

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| OMON | (FunctionStub) | function-stub | engine/functions/derivative/omon.py | yfinance (options chain) | yes (via stub option controls) | no (table only) | Options Monitor; mock exists |
| OVME | (FunctionStub) | function-stub | engine/functions/derivative/ovme.py | yfinance, fred (rate) + Black-Scholes / Heston | yes (full option-assumption controls) | no | Option valuation; mock exists |
| OVDV | (FunctionStub) | function-stub | engine/functions/fx/_funcs.py | reference_fx_vol_smile_model | no | no | FX vol smile; mock exists |
| IVOL | (FunctionStub) | function-stub | engine/functions/derivative/_stubs.py | yfinance | no | no | Implied vol; mock exists |
| OSA | (FunctionStub) | function-stub | engine/functions/derivative/_stubs.py | yfinance + Black-Scholes | yes (option controls) | no | Option strategy analyzer |
| HVT | (FunctionStub) | function-stub | engine/functions/derivative/_stubs.py | yfinance | no | no | Historical volatility |
| GREEKS (duplicate row) | see Portfolio | | | | | | |

## Equities

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| DES | ui/src/functions/DES.tsx | bespoke | engine/functions/equity/des.py | yfinance + coingecko (CRYPTO) + finnhub | yes | n/a (KPI/profile) | CRITICAL; multi-asset aware |
| FA | ui/src/functions/FA.tsx | bespoke | engine/functions/equity/fa.py | sec_edgar, yfinance | yes | n/a (financial statements) | Bespoke financial-analysis |
| EQS | ui/src/functions/EQS.tsx | bespoke | engine/functions/equity/eqs.py | yfinance (screener model) | yes | n/a (table) | Equity Screener |
| WACC | ui/src/functions/WACC.tsx | bespoke | engine/functions/equity/wacc.py | yfinance, fred, damodaran | yes | partial (3×3 heat grid for β/Rd) | OK shape |
| DVD | ui/src/functions/DVD.tsx | bespoke | engine/functions/equity/dvd.py | yfinance | yes | n/a (calendar table) | Dividend |
| DPF | ui/src/functions/DPF.tsx | bespoke | engine/functions/equity/dpf.py | finra (ATS) | yes | n/a (table) | Dark pool flow |
| ESG | ui/src/functions/ESG.tsx | bespoke | engine/functions/equity/esg.py | yfinance | yes | n/a | ESG scores |
| EE | ui/src/functions/EE.tsx | bespoke | engine/functions/equity/ee.py | finnhub, yfinance | yes | n/a (calendar) | Earnings Events |
| EREV | ui/src/functions/EREV.tsx | bespoke | engine/functions/equity/erev.py | finnhub | yes | n/a (table) | Earnings Revisions |
| TRQA | ui/src/functions/TRQA.tsx | bespoke | engine/functions/news/trqa.py | transcripts archive + local extractive QA | yes (transcript text) | n/a | Earnings Call Q&A |
| TSAR | ui/src/functions/TSAR.tsx | bespoke | engine/functions/news/tsar.py | transcripts_archive | yes | n/a (timeline) | Transcript archive |
| ANR | ui/src/functions/anr_pane/index.tsx | bespoke | engine/functions/equity/anr.py | finnhub, yfinance | yes | yes (analyst rating bars/heat) | Analyst Ratings |
| FTS | (FunctionStub) | function-stub | engine/functions/equity/fts.py | sec_efts | no | no | SEC full-text search |
| FORM4 | (FunctionStub) | function-stub | engine/functions/equity/form4.py | sec_edgar, yfinance | no | no | Insider Form 4 filings |
| CACT | (FunctionStub) | function-stub | engine/functions/equity/cact.py | sec_edgar, yfinance | no | no | Corporate actions; mock exists |
| HDS | (FunctionStub) | function-stub | engine/functions/equity/hds.py | yfinance (holders) | no | no | Mock exists |
| HFS | (FunctionStub) | function-stub | engine/functions/equity/hfs.py | sec_13f | no | no | Hedge fund stalker; mock exists |
| PIB | (FunctionStub) | function-stub | engine/functions/equity/pib.py | sec_edgar | no | no | Private/insider briefs |
| SPLC | (FunctionStub) | function-stub | engine/functions/equity/splc.py | sec_edgar | no | no | Supply chain |
| DCF | (FunctionStub) | function-stub | engine/functions/equity/dcf.py | yfinance | no | no | DCF model; mock exists |
| DCFS | (FunctionStub) | function-stub | engine/functions/equity/dcfs.py | yfinance + sensitivity model | no | no | DCF sensitivity; mock exists |
| DDM | (FunctionStub) | function-stub | engine/functions/equity/dcf.py (DDMFunction) | yfinance | no | no | Dividend discount; mock exists |
| BETA | (FunctionStub) | function-stub | engine/functions/equity/beta.py | yfinance | no | no | Beta calculator |
| DARK | (FunctionStub) | function-stub | engine/functions/equity/dark.py | finra | no | no | Dark pool model fallback common |
| RV | (FunctionStub) | function-stub | engine/functions/equity/rv.py | finnhub, yfinance | no | no | Relative value |
| WB (duplicate row) | see Bonds | | | | | | |

## FX

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| FXH | (FunctionStub) | function-stub | engine/functions/fx/fxh.py | yfinance | no | no | FX history |
| FXFC | (FunctionStub) | function-stub | engine/functions/fx/_funcs.py | yfinance + covered-interest-parity formula | no | no | FX forward curve |
| FXIP | (FunctionStub) | function-stub | engine/functions/fx/_funcs.py | yfinance + covered-interest-parity + reference policy rate | no | no | FX interest parity |
| FRD | (FunctionStub) | function-stub | engine/functions/fx/_funcs.py | yfinance + ecb + formulas | no | no | FX rate differential |
| WCRS (duplicate) | see Charts/Tech | | | | | | |
| OVDV (duplicate) | see Derivatives | | | | | | |

## Macro

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| ECO | ui/src/functions/ECO.tsx | bespoke | engine/functions/macro/eco.py | tradingeconomics | yes | n/a (calendar) | Economic calendar |
| ECST | ui/src/functions/ECST.tsx | bespoke | engine/functions/macro/ecst.py | fred, worldbank | yes | yes (lightweight-charts time series) | Economic statistics |
| ECFC | ui/src/functions/ECFC.tsx | bespoke | engine/functions/macro/ecfc.py | imf, oecd | yes | n/a (forecast table) | Economic forecasts |
| GMM | (FunctionStub) | function-stub | engine/functions/macro/gmm.py | tradingeconomics | no | no | Global macro monitor |
| REGM | (FunctionStub) | function-stub | engine/functions/macro/regm.py | fred, yfinance | no | no | Regime classifier |
| TRDH | (FunctionStub) | function-stub | engine/functions/macro/trdh.py | exchange_calendars | no | no | Trading hours |
| COUN | (FunctionStub) | function-stub | engine/functions/macro/coun.py | country_reference_profile (internal) | no | no | Country profile |
| WIRP (duplicate) | see Bonds | | | | | | |
| BTMM (duplicate) | see Charts/Tech | | | | | | |

## News / Intelligence

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| TOP | ui/src/functions/TOP.tsx | bespoke | engine/functions/news/top.py | rss, gdelt, finnhub_news | yes | n/a (feed list) | Top news feed |
| NI | ui/src/functions/NI.tsx | bespoke | engine/functions/news/ni.py | rss, gdelt | yes | n/a (feed) | CRITICAL; News Intelligence |
| CN | ui/src/functions/NI.tsx (CN aliases to NI) | bespoke | engine/functions/news/cn.py | rss, finnhub_news, yfinance, gdelt | yes | n/a | CRITICAL; Company News (same UI as NI) |
| INSTANT | ui/src/functions/INSTANT.tsx | bespoke | server_routes/instant.py | rss (priority polling) + xai injection | yes | n/a | LiveSquawk-style line |
| XSEN | ui/src/functions/XSEN.tsx | bespoke | server_routes/xai.py | brave→twitter syndication scrape + RoBERTa (`showme_x_v1`) | yes | n/a | X-sentiment + bullish score |
| AV | (FunctionStub) | function-stub | engine/functions/news/av.py | podcast_rss | no | no | Audio/Podcast feed |
| EVTS | (FunctionStub) | function-stub | engine/functions/news/evts.py | yfinance | no | no | Corporate events |
| NSE | (FunctionStub) | function-stub | engine/functions/news/nse.py | rss (when wired) | no | no | News Stream Engine |
| TRAN | ui/src/functions/TRAN.tsx | bespoke | engine/functions/news/tran.py | seekingalpha (transcripts) | yes | n/a | Transcripts (Sub list) |
| NALRT | (FunctionStub) | function-stub | engine/functions/news/nalrt.py | rss (probed) | no | no | News Alert |
| SOSC | (FunctionStub) | function-stub | engine/functions/news/sosc.py | stocktwits, reddit | no | no | Social Sentiment |

## Screening

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| SCAN | ui/src/functions/SCAN.tsx | bespoke | server_routes/scanner.py + engine/services/scanner_service.py | yfinance, ccxt | yes | yes (DataGrid + Sparklines) | CRITICAL |
| MIS | ui/src/functions/MIS.tsx | bespoke | server_routes/mis.py | yfinance, ccxt | yes | yes (per-row TF strip + progress) | CRITICAL; 23-indicator consensus |
| WATCH | ui/src/functions/WATCH.tsx | bespoke | server_routes/watchlists.py | yfinance, ccxt | yes | yes (Sparkline rows) | CRITICAL |
| ALRT | ui/src/functions/ALRT.tsx | bespoke | engine/functions/misc/alrt.py + engine/services/alert_engine.py | local alert engine | yes | n/a | Alert management |
| MOST | ui/src/functions/MOST.tsx | bespoke | engine/functions/screen/_funcs.py (MOSTFunction) | yfinance | yes | yes (table with sparkline) | Most actives/changers |
| WEI | ui/src/functions/WEI.tsx | bespoke | engine/functions/screen/_funcs.py (WEIFunction) | yfinance | yes | yes (per-row Sparkline) | World equity indices |
| MAP | ui/src/functions/MarketHeatmap.tsx | bespoke | engine/functions/screen/wmap.py | yfinance | yes (mode/period tabs) | yes (HeatCell grid) | Market heatmap |
| SECT | ui/src/functions/MarketHeatmap.tsx | bespoke (same component as MAP) | engine/functions/screen/sect.py | yfinance | yes | yes (HeatCell grid) | Sector heatmap |
| ICX | (FunctionStub) | function-stub | engine/functions/screen/icx.py | yfinance | no | no | Index components |
| MICRO | (FunctionStub) | function-stub | engine/functions/screen/micro.py | yfinance | no | no | Microcap screener |
| FRH | (FunctionStub) | function-stub | engine/functions/screen/frh.py | yfinance | no | no | Fixed-rate hunter |
| SRCH | (FunctionStub) | function-stub | engine/functions/screen/_funcs.py | none | no | no | Generic search stub |
| FSRC | (FunctionStub) | function-stub | engine/functions/screen/_funcs.py | none | no | no | Fund search |
| CSRC | (FunctionStub) | function-stub | engine/functions/screen/_funcs.py | none | no | no | Crypto search |
| SECF | (FunctionStub) | function-stub | engine/functions/screen/_funcs.py | none | no | no | SEC filings finder |

## Misc

| Code | Current UI Pane File | Pane Type | Backend Handler | Provider(s) | Has Real Controls | Real Chart Grammar | Notes |
|------|----------------------|-----------|-----------------|-------------|-------------------|--------------------|-------|
| WHAL | ui/src/functions/WHAL.tsx | bespoke | engine/functions/misc/whal.py | binance public agg trades, yfinance, sec_edgar | yes | n/a | Whale flow monitor |
| ONCH | (FunctionStub) | function-stub | engine/functions/misc/onch.py | mempool, etherscan | no | no | On-chain monitor |
| POLY | (FunctionStub) | function-stub | engine/functions/misc/poly.py | polymarket | no | no | Polymarket reference |
| SAT | (FunctionStub) | function-stub | engine/functions/misc/sat.py | sentinelhub | yes (range) | no | Satellite imagery |
| CDE | (FunctionStub) | function-stub | engine/functions/misc/cde.py | none | no | no | INTENT-UNCLEAR |
| BIO | ui/src/functions/BIO.tsx | bespoke | engine/functions/misc/_extras.py (BIOFunction) | showme_curriculum (internal) | yes | n/a | Biography/education |
| LITM | (FunctionStub) | function-stub | engine/functions/misc/_bonus.py (LITMFunction) | sec_edgar (live), yfinance | no | no | Mock exists |
| MOSS | (FunctionStub) | function-stub | engine/functions/misc/_bonus.py (MOSSFunction) | yfinance | no | no | Mock exists |
| CHGS | (FunctionStub) | function-stub | engine/functions/misc/_bonus.py | yfinance | no | no | Changes monitor |
| APPL | (FunctionStub) | function-stub | engine/functions/misc/_bonus.py | yfinance | no | no | Applications/launches |
| BMC | (FunctionStub) | function-stub | engine/functions/misc/_extras.py | none | no | no | Mock exists; INTENT-UNCLEAR |
| FLY | (FunctionStub) | function-stub | engine/functions/misc/_extras.py | opensky | no | no | Flight monitor |
| DINE | (FunctionStub) | function-stub | engine/functions/misc/_extras.py | openstreetmap_nominatim | no | no | Dining picker |
| MARS | (FunctionStub) | function-stub | engine/functions/portfolio/_more.py | none | no | no | INTENT-UNCLEAR |
| TRA | (FunctionStub) | function-stub | engine/functions/portfolio/_more.py | yfinance | no | no | Trade analysis stub |
| TLDR (dup) | see News | | | | | | |

## Missing (declared in design-export catalogue but with NO backend handler)

| Code | Notes |
|------|-------|
| AGENT | Has bespoke UI, no engine FunctionRegistry entry — uses agent route directly |
| ASK | Has bespoke UI, no engine FunctionRegistry entry — uses ask route directly |
| BDA | Has bespoke UI, no engine entry — assistant route |
| BOT/BOTS/PERF/STRA/TMPL/INDX/CONN/MIS/WATCH/INSTANT/XSEN | Bespoke UI, no engine FunctionRegistry entry — own routes |
| HOME | Welcome dashboard, not a function |
| KEYB, CATALOG, MEET (partial) | Catalog-only; no real backend or only mock |
| FXGO, BBGT | Trade/desk reference stubs; INTENT-UNCLEAR |
| CRPR, DDIS, DEBT, ALLQ | Bond _stubs.py reference-only; INTENT-UNCLEAR |

---

### Aggregate counts

- 141 unique codes catalogued.
- **30 bespoke** UI panes (incl. CN aliased to NI, MAP/SECT shared MarketHeatmap).
- **0 template-only** panes resolved at runtime (TemplateRenderer is still mounted but Workspace's switch only invokes it when `resolvePaneRenderer` returns `"template"`; today every code resolves to `native` or `stub`).
- **111 function-stub** panes (everything else: catalog codes without a bespoke UI fall through to `FunctionStub` since the 2026-05-23 collapse of design-export → stub).
- **0 design-export** rendered panes (rendering tier dead in product path; only Preferences uses `SettingsDesignExportRenderer` legitimately).
- **0 missing critical**: every CRITICAL_CODE (GP, HP, DES, WATCH, SCAN, PORT, TOP, NI, CN, MIS) has a bespoke native pane today.
