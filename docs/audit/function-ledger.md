# Function ledger — B1 + offline gate + B2 deep review

Generated: 2026-11-08T00:35:02.950724+00:00

- Functions: 142; B2 reviewed: 142; independent recomputation passed / failed / not done: 56 / 76 / 10
- Status: confirmed = verifier could not refute (its severity wins); upheld/rejected = arbiter ruling; disputed = no ruling; reported = P2/P3 single reviewer.

## Findings by status and final severity

| Status | P0 | P1 | P2 | P3 | REJECTED |
|---|---:|---:|---:|---:|---:|
| confirmed | 34 | 134 | 46 | 1 | 0 |
| upheld | 0 | 0 | 1 | 0 | 0 |
| disputed | 0 | 0 | 0 | 0 | 0 |
| unverified | 0 | 0 | 0 | 0 | 0 |
| reported | 0 | 0 | 346 | 129 | 0 |
| rejected | 0 | 0 | 0 | 0 | 0 |

## Confirmed / upheld P0–P1 (fix first)

| Code | Core | Sev | Status | Finding | Where |
|---|---|---|---|---|---|
| FA | yes | P1 | confirmed | Stale 2010/2016 values shown as latest balance and cash-flow items | backend/showme/engine/data_sources/equity/sec_edgar_adapter.py:158 (if key in ca |
| FA | yes | P1 | confirmed | Quarterly and YTD facts mixed into annual statement rows | backend/showme/engine/data_sources/equity/sec_edgar_adapter.py:161-166; backend/ |
| FA | yes | P0 | confirmed | yfinance fallback fetched then discarded for empty SEC result | backend/showme/engine/functions/equity/fa.py:50 (if not sec_data), fa.py:64 (if  |
| TOP | yes | P0 | confirmed | TOP stays in warming envelope; no headlines via /api/fn | backend/showme/server_routes/function_index.py:49-145 (SWR warming branch); back |
| ACCT |  | P0 | confirmed | Quote failure silently books avg_cost as market price | backend/showme/engine/functions/portfolio/acct.py:112-134 (fallback at 127 and 1 |
| BMTX |  | P1 | confirmed | RSI mean-reversion closes longs inside its hold band | backend/showme/engine/services/backtest_framework.py:226-241 (return at 240); Ba |
| BMTX |  | P0 | confirmed | Non-existent tickers produce an ok matrix with fabricated backtests | backend/showme/engine/functions/portfolio/bmtx.py:97-104 (template history, no w |
| CORR |  | P0 | confirmed | Default LIVE universe collapses to one symbol because weekday series are dropped as null-heavy | backend/showme/engine/functions/portfolio/corr.py:24 (threshold), 240-270 (_drop |
| CORR |  | P1 | confirmed | Annualized volatility uses sqrt(252) for 24/7 crypto, understating it by about 17% | backend/showme/engine/functions/portfolio/corr.py:490-491, 525, 844, 855-875, 99 |
| CORR |  | P1 | confirmed | Ref mode shows a green live pill | ui/src/functions/CORR.tsx:304-306 (liveSourceMode), 573-579 (pill tone and text) |
| COUN |  | P0 | confirmed | TR Real GDP is a constant synthetic series reported as FRED data | backend/showme/engine/functions/macro/coun.py:66-70 (live_sources adds fred unco |
| CPF |  | P0 | confirmed | European gas series served with Henry Hub futures prices | backend/showme/engine/functions/commodity/_funcs.py:792 (PNGASEUUSDM mapped to N |
| CPF |  | P1 | confirmed | Futures proxy reported as live_official | backend/showme/engine/functions/commodity/_funcs.py:921 and :938 (data_mode); ui |
| CRPR |  | P0 | confirmed | CRPR pane cannot show any equity issuer: symbol routing hits a BOND-only guard | backend/showme/engine/functions/bond/_stubs.py:201; backend/showme/manifest/seed |
| CRPR |  | P0 | confirmed | Sovereign path returns a hard-coded AA+ labelled as model_implied | backend/showme/engine/functions/bond/_stubs.py:251-262 (rating 'AA+' at 253; imp |
| CRPR |  | P1 | confirmed | Interest coverage divides current EBITDA by a three-year-old interest expense | backend/showme/engine/functions/bond/_stubs.py:324, 329 |
| CRPR |  | P1 | confirmed | Fact picker ignores duration and form, so YTD or quarterly flows can become the EBITDA input | backend/showme/engine/functions/bond/_stubs.py:140-159 (picker), 322-323 (operat |
| DARK |  | P0 | confirmed | DARK always reports stale data because the FINRA query returns the oldest 200 rows | C:/Users/Kullanıcı/showme/backend/showme/engine/functions/equity/dark.py:274-287 |
| DCF |  | P0 | confirmed | DCF pane always overrides provider FCFE and shares with placeholder inputs | C:/Users/Kullanıcı/showme/ui/src/functions/DCF.tsx:85-86 (defaults 10_000 and 15 |
| DPF |  | P0 | confirmed | Returns 2023 FINRA weeks as current because the limit cuts the oldest rows | backend/showme/engine/functions/equity/dpf.py:130 (limit=weeks*4); backend/showm |
| DPF |  | P1 | confirmed | Fabricated ATS volume shown when FINRA has no rows | backend/showme/engine/functions/equity/dpf.py:58-75 (_fallback_rows), :172 (fall |
| ECFC |  | P0 | confirmed | EUR option returns provider_unavailable because IMF keys the euro area as EURO | backend/showme/engine/functions/macro/ecfc.py:44-55 (_ISO2_TO_ISO3 has no EUR/EU |
| ECST |  | P0 | confirmed | Unknown series ids are served a synthetic constant series as data | backend/showme/engine/functions/macro/ecst.py:158-161 (baseline when df empty),  |
| ECST |  | P1 | confirmed | Compare overlay forward-fills a monthly series onto daily dates | backend/showme/engine/functions/macro/ecst.py:197-199 (outer merge, ffill().bfil |
| FTS |  | P0 | confirmed | Snippet evidence is the state of incorporation, not matched filing text | backend/showme/engine/data_sources/equity/sec_efts_adapter.py:77; backend/showme |
| FTS |  | P0 | confirmed | Other issuers' filings labelled as AAPL | backend/showme/engine/functions/equity/fts.py:26 (prepends instrument symbol), f |
| FXGO |  | P1 | confirmed | Stale Yahoo quote labelled live and stamped with fetch time | backend/showme/engine/functions/trade/_funcs.py:517 (mid), 645-657 (data_mode/st |
| FXGO |  | P1 | confirmed | previous_close is the close five sessions back, not the prior session | backend/showme/engine/functions/trade/_funcs.py:518-520, 556 and change/change_p |
| FXGO |  | P0 | confirmed | yfinance-style pair tickers (GBPUSD=X) are corrupted and 404 | backend/showme/engine/functions/trade/_funcs.py:479 (strip order), 498 (call sit |
| ISIN |  | P0 | confirmed | Multi-identifier lookups time out and return nothing | C:/Users/Kullanıcı/showme/backend/showme/engine/data_sources/reference/openfigi_ |
| LITM |  | P0 | confirmed | LITM reports no events for AAPL/TSLA although matching 8-K items exist | backend/showme/engine/functions/misc/_bonus.py:55 (max_documents default 1), :58 |
| LOTS |  | P0 | confirmed | LOTS open and sell fail through /api/fn because the route strips the symbol they read | backend/showme/engine/functions/portfolio/lots.py:26 and 35; backend/showme/serv |
| LOTS |  | P1 | confirmed | Manifest claims broker-sourced tax lots with credential and status inputs that the handler does not have | backend/showme/manifest/seeds/lots_seed.py:1-5, 52-104, 122-135, 166-179; backen |
| MOST |  | P1 | confirmed | Equity and ETF change percent is computed against a close about six sessions old, flipping signs | backend/showme/quotes.py:541-545 (_fetch_yahoo_chart_quote, range 5d; prev = pre |
| MOST |  | P0 | confirmed | Cold live scan returns an empty payload even though data exists | backend/showme/engine/functions/screen/_funcs.py:393-481 (live budget path); wra |
| MOST |  | P1 | confirmed | Live label and as_of stamp are false on a closed market (Sunday) | backend/showme/engine/functions/screen/_funcs.py:2225 (as_of = datetime.now); :2 |
| NSE |  | P0 | confirmed | Free-text company-name search returns nothing when no symbol is bound | backend/showme/engine/functions/news/nse.py:71-95 (RSS query with terms from _qu |
| OVDV |  | P0 | confirmed | Surface labelled implied vol is realized vol plus an invented smile; RR/BF cards are fabricated | ui/src/functions/OVDV.tsx:485-487 and 513; backend/showme/engine/functions/fx/_f |
| OVDV |  | P1 | confirmed | Headline 25-delta risk reversal has the wrong sign whenever the 1W-to-1M slope is negative | backend/showme/engine/functions/fx/_funcs.py:467-470 (slope_sign) vs 502 (head_r |
| OVDV |  | P1 | confirmed | User-quoted ATM 7.00 percent is shown as 7.15 percent, and an invented term ramp is added | backend/showme/engine/functions/fx/_funcs.py:675-678 (curve = atm + i*0.0015) an |
| PORT_WHATIF |  | P0 | confirmed | Pane default fabricates a $100 cost and reports a fake P&L gain for any symbol | ui/src/functions/PortfolioAnalytics.tsx:245-246,1037-1038; backend/showme/engine |
| PORT_WHATIF |  | P1 | confirmed | What-if never debits cash, so hypothetical equity is overstated by the full notional | backend/showme/engine/functions/portfolio/_more.py:46-49,56-60 |
| PORT_WHATIF |  | P1 | confirmed | Missing cost defaults to zero, so the whole position value shows as a gain | backend/showme/engine/functions/portfolio/_more.py:32-33,46-48,56-58 |
| PSC |  | P0 | confirmed | Sizing with no symbol silently uses BTCUSDT's live price as entry | backend/showme/engine/functions/psc.py:137-138,82-96; backend/showme/engine/func |
| SAT |  | P0 | confirmed | Selected AOI is silently replaced by San Francisco Bay | backend/showme/server_routes/_agent_runtime.py:365-372 (SAT routed defaults with |
| SAT |  | P0 | confirmed | Blank GIBS tile presented as the latest capture | backend/showme/engine/functions/misc/sat.py:88 (capture_date = date_to), sat.py: |
| TAUC |  | P0 | confirmed | Live TreasuryDirect path always returns zero auctions | backend/showme/engine/data_sources/bond/treasury_auctions_adapter.py:42 (auction |
| TCA |  | P0 | confirmed | Unfilled limit orders are booked as executed fills | backend/showme/engine/functions/trade/tca.py:386-388, 391, 398, 410-432 (_avg_fi |
| TCA |  | P1 | confirmed | Benchmark is a 5-day VWAP, not the fill session's VWAP | backend/showme/engine/functions/trade/tca.py:489, 483, 29-31, 52, 200-205 |
| TCA |  | P1 | confirmed | TWAP and ARRIVAL selections do not change the benchmark | backend/showme/engine/functions/trade/tca.py:200-205 |
| TLDR |  | P0 | confirmed | Portfolio mode summarises peer crypto group, not the user's portfolio | backend/showme/engine/functions/news/tldr.py:35-44 (symbols then PortfolioState  |
| TLDR |  | P1 | confirmed | Daily % change computed against the wrong reference close | backend/showme/quotes.py:528 (params range 5d) and 542-552 (prev from chartPrevi |
| TLDR |  | P0 | confirmed | Calendar reported as 0 scheduled when the calendar call failed | backend/showme/engine/functions/news/tldr.py:116 (top.data slicing), 132 (eco.da |
| TRA |  | P0 | confirmed | Dividends reported as zero for dividend-paying stocks | backend/showme/engine/data_sources/equity/yfinance_adapter.py:430 (events reques |
| TRA |  | P1 | confirmed | TWR and CAGR labelled total return but are price-only | backend/showme/engine/functions/portfolio/_more.py:179-180 (TWR from raw close), |
| TSOX |  | P0 | confirmed | TSOX default and quick-pick Treasury futures are rejected as unsupported | backend/showme/server.py:905, 113, 115; backend/showme/manifest/seeds/tsox_seed. |
| WETR |  | P0 | confirmed | Asia East and EU NW show New York weather | backend/showme/engine/functions/commodity/_funcs.py:151-176 (LOCATION_PRESETS ha |
| CN | yes | P1 | confirmed | CoinGecko profile row is stamped with the call time and tagged BTCUSDT | backend/showme/engine/functions/news/cn.py:546 (symbol hard-coded), :548 (publis |
| DES | yes | P1 | confirmed | BTC '52-week' high/low are the all-time high and low | backend/showme/engine/functions/equity/des.py:156-157 (fallback to ath/atl), :19 |
| ECO | yes | P1 | confirmed | Forex Factory K/M suffix is applied and also kept as the unit, so values are 1000x too large | backend/showme/engine/functions/macro/eco.py:490-506 (multiplier applied at :498 |
| GP | yes | P1 | confirmed | RSI seed sums gains and losses instead of averaging, skewing RSI on short windows | ui/src/functions/GP.tsx:752-783 (seed at :762); ui/src/functions/HP.tsx:862-885 |
| GP | yes | P1 | confirmed | 4h interval returns 1-hour bars labelled 4H | backend/showme/chart_history.py:52 and fetch_yahoo_history; backend/showme/engin |
| HP | yes | P1 | confirmed | RSI, MACD and ATR are computed on newest-first bars, so the values and MACD sign are wrong | ui/src/functions/HP.tsx:126, 611, 783-799 (decorate), 862-885 (rsiSeries), 958+  |
| MAP | yes | P1 | confirmed | World heatmap 1D change is a multi-session move | backend/showme/engine/functions/screen/wmap.py:145-170; backend/showme/quotes.py |
| OMON | yes | P1 | confirmed | ITM puts show IV 0.0 and delta -1.0 from a solver-failure IV | backend/showme/engine/functions/derivative/omon.py:287,294-300 |
| OMON | yes | P1 | confirmed | As-of timestamp and live label are not true | backend/showme/engine/functions/derivative/omon.py:406,409-410; ui/src/functions |
| WIRP | yes | P1 | confirmed | Hike/cut probabilities built from T-bill vs target basis but labelled live futures | backend/showme/engine/functions/macro/wirp.py:66-67 (labels), :137 (^IRX as impl |
| AIM |  | P1 | confirmed | Submitted orders are not counted or shown as open | backend/showme/engine/functions/trade/_funcs.py:352; ui/src/functions/AIM.tsx:87 |
| ALLQ |  | P1 | confirmed | Bond mid anchored to a historical average coupon, not a market yield | backend/showme/engine/functions/bond/_stubs.py:759-789 (rec value at 776, ref_yi |
| ALLQ |  | P1 | confirmed | Tenor ignored on the FiscalData fallback: US2Y and US10Y give the same mid | backend/showme/engine/functions/bond/_stubs.py:770-772 (type selection), 782 (ye |
| ALLQ |  | P1 | confirmed | Per-tenor Treasury anchor never runs: configured base_url returns HTTP 404, failure swallowed silently | backend/config/data_sources.yaml:117-118; backend/showme/engine/data_sources/bon |
| ALLQ |  | P1 | confirmed | Synthetic composite quotes are stamped live_official with a fabricated quote time | backend/showme/engine/functions/bond/_stubs.py:865-879 (rows), 883 (spread defau |
| ANR |  | P1 | confirmed | ANR stamps the fetch date as the rating and target as-of date | C:/Users/Kullanıcı/showme/backend/showme/engine/functions/equity/anr.py:47-49, 1 |
| AV |  | P1 | confirmed | BTC-USD shows global podcast episodes under an 'Audio / Video Archive - BTCUSD' header | backend/showme/engine/functions/news/av.py:164-170 (fallback), :401 (warning); u |
| BBGT |  | P1 | confirmed | Treasury futures classified as EQUITY, so live routing goes to the equity broker | backend/showme/server.py:905 (return EQUITY), server.py:113, server.py:115; back |
| BGAS |  | P1 | confirmed | as_of is the fetch time, not the quote time | backend/showme/engine/data_sources/equity/yfinance_adapter.py:252 and :274 (time |
| BGAS |  | P1 | confirmed | BGAS identity mismatch: gasoline seed, natural-gas title, any contract served | backend/showme/manifest/seeds/bgas_seed.py:44 (name Benchmark Gasoline Futures)  |
| BIO |  | P1 | confirmed | Static 'native_bridge_available' and data_state 'live' on a non-macOS host | backend/showme/engine/functions/misc/_extras.py:137-177 (rows 138-154, methodolo |
| BLAK |  | P1 | confirmed | Effective lookback is 120 days, not the declared 1Y or the 504-day default | backend/showme/server_routes/_agent_runtime.py:289-290 and 787; backend/showme/e |
| BLAK |  | P1 | confirmed | market_cap_data_state reads real when most weights are zero | backend/showme/engine/functions/portfolio/blak.py:133-137 and 374; warning logic |
| BLAK |  | P1 | confirmed | Seed declares Ledoit-Wolf shrinkage that the code never applies | backend/showme/manifest/seeds/blak_seed.py:88-93 and 158; backend/showme/engine/ |
| BOIL |  | P1 | confirmed | Brent card and chart use WTI history | backend/showme/engine/functions/commodity/_funcs.py:594-595 (chart_history taken |
| BOIL |  | P1 | confirmed | as_of is the fetch time, not the quote time | backend/showme/engine/data_sources/equity/yfinance_adapter.py:252 and :274; ui/s |
| BQL |  | P1 | confirmed | with(start, end) window is ignored in live mode | C:/Users/Kullanıcı/showme/backend/showme/engine/functions/api/bql.py:257-260; C: |
| BQUANT |  | P1 | confirmed | Notebook reported ready with no Jupyter runtime; caller flag trusted | C:/Users/Kullanıcı/showme/backend/showme/engine/functions/api/bquant.py:20-22 (p |
| BRIEF |  | P1 | confirmed | Brief is not portfolio-aware; default watchlist is hard-coded | backend/showme/engine/functions/news/brief.py:38 (hard-coded default); ui/src/fu |
| BTMM |  | P1 | confirmed | Stale and legacy rows shown as current rates and averaged | backend/showme/engine/functions/macro/btmm.py:701 (hottest, no freshness gate),  |
| CACT |  | P1 | confirmed | Dividend history has 21 missing events and two duplicated splits | C:/Users/Kullanıcı/showme/backend/showme/engine/functions/equity/cact.py:142, 15 |
| CDE |  | P1 | confirmed | Trailing tokens and unbalanced parentheses are silently dropped, so stored formulas evaluate a different expression | backend/showme/engine/functions/equity/eqs.py:180-181 (parse_dsl returns [0] and |
| CSRC |  | P1 | confirmed | Chg% is a 4-session change labelled as day change | backend/showme/quotes.py:528-551 (chartPreviousClose at 541-546); consumed by ba |
| DCFS |  | P1 | confirmed | FCFE cash flows discounted at WACC | backend/showme/engine/functions/equity/dcf.py:120-134 (wacc), :147 (freeCashflow |
| DDM |  | P1 | confirmed | D0 taken from forward dividendRate, then grown again | backend/showme/engine/functions/equity/dcf.py:43 (dividendRate first), :63 (D1 = |
| DDM |  | P1 | confirmed | Sensitivity surface holds D1 fixed across growth columns | backend/showme/engine/functions/equity/dcf.py:78-86 |
| EE |  | P1 | confirmed | Last actual and last estimate KPIs read the upcoming, unreported quarter | ui/src/functions/EE.tsx:358 (lastActual = rows[0]), :359-363 (lastEstimate/lastS |
| EE |  | P1 | confirmed | Reference template is fabricated and internally inconsistent | backend/showme/engine/functions/equity/ee.py:106-140 (_earnings_template), :110  |
| EMSX |  | P1 | confirmed | Same ZN=F misclassification affects EMSX routing | backend/showme/server.py:905; backend/showme/engine/functions/trade/_funcs.py (_ |
| ESG |  | P1 | confirmed | Proxy methodology claims term frequency over recent 10-Ks; code counts all-year filing hits | backend/showme/engine/functions/equity/esg.py:28-34 (methodology), esg.py:49-62  |
| EVTS |  | P1 | confirmed | Non-date scalars written into the date column and sorted to the top | backend/showme/engine/functions/news/evts.py:117 (date from _date_value), :200-2 |
| EXEC |  | P1 | confirmed | Simulated schedule labelled live_exchange | backend/showme/engine/functions/trade/exec.py:498 (also 503 execution_mode) |
| EXEC |  | P1 | confirmed | Arrival price is the end of the replay window (look-ahead) | backend/showme/engine/functions/trade/exec.py:429-430 (arrival default), 133-134 |
| EXEC |  | P1 | confirmed | horizon_seconds is not honoured; slices are mapped to 55 minutes of bars | backend/showme/engine/functions/trade/exec.py:119, 148, 137-141 |
| EXEC |  | P1 | confirmed | Open-parent and needs-close cards are hard-coded | backend/showme/engine/functions/trade/exec.py:494-495 |
| FORM4 |  | P1 | confirmed | Net flow reports 0.0 when no transaction direction was parsed | backend/showme/engine/functions/equity/form4.py:332, form4.py:365-368 |
| FORM4 |  | P1 | confirmed | SEC-only path returns hollow rows labelled live_official | backend/showme/engine/functions/equity/form4.py:182-207 (reads reportingOwner, t |
| FORM4 |  | P1 | confirmed | Form 4 document URLs point at data.sec.gov and return 404 | backend/showme/engine/data_sources/equity/sec_edgar_adapter.py:138-143 (url buil |
| FSRC |  | P1 | confirmed | Curated AUM and YTD are stale or wrong and not labelled as reference | backend/showme/engine/functions/screen/_funcs.py:1290-1377 (curated rows); ui/sr |
| GEX |  | P1 | confirmed | Call and put walls are net-GEX extrema, not call/put walls | backend/showme/engine/services/gamma_exposure.py:139-140; backend/showme/engine/ |
| GEX |  | P1 | confirmed | Gamma flip reported as null while standard zero-crossing exists at 758 | backend/showme/engine/services/gamma_exposure.py:127-137; backend/showme/engine/ |
| GLCO |  | P1 | confirmed | Row timestamps are fetch time, not quote time | backend/showme/engine/data_sources/equity/yfinance_adapter.py:252 and :274; _fun |
| GMM |  | P1 | confirmed | Default ALL and G7 universes silently cut to 6 rows | backend/showme/engine/functions/macro/gmm.py:94; backend/showme/server_routes/_a |
| HDS |  | P1 | confirmed | Placeholder holder rows returned for any symbol when live is omitted | backend/showme/engine/functions/equity/hds.py:24 (handler default live=false), h |
| HDS |  | P1 | confirmed | Major-holder summary values emitted as holder rows | backend/showme/engine/functions/equity/hds.py:141-152 (major rows, market_value  |
| HDS |  | P1 | confirmed | 13F enrichment never matches a ticker and drops its fields | backend/showme/engine/functions/equity/hds.py:58-60 (issuer=ticker), hds.py:125- |
| HFS |  | P1 | confirmed | AAPL live HFS returns static reference holders labelled live/sec_13f | backend/showme/engine/functions/equity/hfs.py:92 (status ok), :100 (sources sec_ |
| HVT |  | P1 | confirmed | Crypto realized vol annualized with 252 trading days | backend/showme/engine/functions/derivative/_stubs.py:264,508,526; ui/src/functio |
| IVOL |  | P1 | confirmed | Solver-failure IVs of 0.001 percent shown as real surface cells | backend/showme/engine/functions/derivative/_stubs.py:163-193 (cell filter at 168 |
| MARS |  | P1 | confirmed | Factor set is mislabelled as Fama-French 5-factor and is near-collinear with the market | backend/showme/engine/functions/portfolio/_more.py:249 and 257-264; ui/src/funct |
| MEET |  | P1 | confirmed | Forward calendar empty, status still ok | backend/showme/engine/functions/comm/meet.py:62 (URL), meet.py:1124-1141 (fetch, |
| MEET |  | P1 | confirmed | War/spot classifier flags non-war headlines as high-impact geopolitics alerts | backend/showme/engine/services/world_events.py:214-220 (_WAR_RE), world_rows() w |
| MGN |  | P1 | confirmed | Spot crypto is margined at 10 percent with 10x buying power because any CRYPTO position switches the whole account to crypto_futures | backend/showme/engine/functions/portfolio/mgn.py:190-198 and 80-83; backend/show |
| MGN |  | P1 | confirmed | Default accounts apply Reg T 50 percent to spot BTC, contradicting the module's own crypto_spot rule | backend/showme/engine/services/margin_engine.py:233-238 (auto-create reg_t) and  |
| MGN |  | P1 | confirmed | Manifest and pane claim broker-sourced margin with no client-side modeling; the handler models margin client-side | backend/showme/manifest/seeds/mgn_seed.py:1-6, 41-45, 148-160, 205-217; backend/ |
| MLSIG |  | P1 | confirmed | Strategy Sharpe uses N-bar target signs as returns and in-sample predictions | backend/showme/engine/services/ml_signals.py:96, 108, 119, 133 (pred_full in-sam |
| MLSIG |  | P1 | confirmed | The signal label is derived from test accuracy, not from the current prediction | backend/showme/engine/functions/portfolio/mlsig.py:155-157; backend/showme/engin |
| MLSIG |  | P1 | confirmed | Feature importance is /coefficient/ on unscaled features, so the ranking reflects units | backend/showme/engine/services/ml_signals.py:124-137 (lstsq path) and 158 (sorte |
| MOSS |  | P1 | confirmed | Crypto annualized vol uses sqrt(252), understating 24/7 assets by about 17% | backend/showme/engine/functions/misc/_bonus.py:215 (vol = rets.std() * 252**0.5) |
| NALRT |  | P1 | confirmed | Source weight matches substrings in body text, so ordinary words earn tier-1 credit | backend/showme/engine/services/news_intelligence.py:78 ('ft'), :82 ('the block') |
| NALRT |  | P1 | confirmed | 'by default' triggers the credit-default critical pattern and reaches the alert threshold | backend/showme/engine/services/news_intelligence.py:56 (credit default pattern) |
| NGAS |  | P1 | confirmed | Shared quote path: stale previousClose and fetch-time as_of | backend/showme/engine/data_sources/equity/yfinance_adapter.py:280 and :252/:274; |
| OSA |  | P1 | confirmed | Calendar and diagonal strategies are valued as if all legs expire together | backend/showme/engine/functions/derivative/_stubs.py:357,389-399,429 |
| PEOP |  | P1 | confirmed | Tim Cook shown as current CEO; Wikidata end-date ignored | backend/showme/engine/services/people_search.py:242-253 (_claim_qids: only skips |
| PFA |  | P1 | confirmed | Default PFA output is hardcoded sample data labelled only as model | backend/showme/engine/functions/portfolio/pfa.py:34-43; ui/src/functions/portfol |
| PFA |  | P1 | confirmed | Brinson effects do not reconcile when weights do not sum to 100% | backend/showme/engine/functions/portfolio/pfa.py:47-48,56-58; ui/src/functions/p |
| POLY |  | P1 | confirmed | Liquidity KPI and per-market liquidity double-counted | ui/src/functions/POLY.tsx:194 (m.liquidity += liq per outcome row), :227-229 (to |
| POLY |  | P1 | confirmed | status=all and status=closed return only closed markets | backend/showme/engine/functions/misc/poly.py:36-41 (include_closed and status ma |
| PORT_OPT |  | P1 | confirmed | Risk Parity output is not equal risk contribution | backend/showme/engine/services/optimizer.py:237-257; ui/src/functions/portfolio/ |
| PORT_OPT |  | P1 | confirmed | Sharpe for min-volatility and risk-parity ignores the risk-free rate | backend/showme/engine/services/optimizer.py:141-155,237-257; backend/showme/engi |
| PVAR |  | P1 | confirmed | coverage_pct reports full coverage after positions are silently truncated to max_positions | backend/showme/engine/functions/portfolio/pvar.py:92,106-110,294,304; ui/src/fun |
| REBA |  | P1 | confirmed | Default model mode orders use invented holdings and prices | backend/showme/engine/functions/portfolio/reba.py:227 (current_weights = target  |
| REBA |  | P1 | confirmed | Live current weights sum to 113 percent | backend/showme/engine/functions/portfolio/reba.py:145-147; ui/src/functions/Port |
| REGM |  | P1 | confirmed | Unknown ticker returns status ok with data_state live | backend/showme/engine/functions/macro/regm.py:91-99 (no emptiness check), 110-13 |
| RPAR |  | P1 | confirmed | ERC solver returns non-equal risk contributions | backend/showme/engine/services/risk_parity.py:49-50 (stop rule), 54-55 (update) |
| RPAR |  | P1 | confirmed | Lookback silently replaced by a sidecar default merge (days 120) | backend/showme/server_routes/function_index.py:74; backend/showme/server_routes/ |
| RPAR |  | P1 | confirmed | Manifest methodology claims ledoit_wolf and risk-target scaling that the code never implements | backend/showme/manifest/seeds/rpar_seed.py:140-145 (defaults) and 202-215 (metho |
| RV |  | P1 | confirmed | Dividend yield is displayed 100x too large | ui/src/functions/RV.tsx:422-427 (fmtRatioPct); backend/showme/engine/functions/e |
| SOSC |  | P1 | confirmed | FinBERT blend is dead code; methodology claims it runs | backend/showme/engine/functions/news/sosc.py:47-53 (_finbert), 218-238 (analyze_ |
| SRSK |  | P1 | confirmed | Unmapped or failed countries get a flat 3.25% spread that becomes a numeric PD | backend/showme/engine/functions/bond/srsk.py:285-287 and 303; ui/src/functions/S |
| STRS |  | P1 | confirmed | Scaling produces negative market values (no -100 percent floor) | backend/showme/engine/services/stress_scenarios.py:213-214 |
| STRS |  | P1 | confirmed | Sector shocks never reach positions (off by default and taxonomy mismatch) | backend/showme/engine/functions/portfolio/strs.py:70-72 and 81 (include_sectors  |
| STRS |  | P1 | confirmed | Bond ETF shocked as equity (TLT wrong sign in COVID) | backend/showme/engine/services/stress_scenarios.py:36 (GFC ETF -0.50) and 52 (CO |
| STRS |  | P1 | confirmed | Manifest claims historical replay that is not implemented | backend/showme/manifest/seeds/strs_seed.py:204-217 (methodology); backend/showme |
| TECH |  | P1 | confirmed | ADX does not apply Wilder's rule that only the larger directional movement counts | backend/showme/engine/functions/chart/tech.py:63-72 (DM at :65-66) |
| TECH |  | P1 | confirmed | 4h requests return 1-hour bars labelled 4h | backend/showme/engine/functions/chart/tech.py:184, 320; backend/showme/chart_his |
| TECH |  | P1 | confirmed | Empty history with data.status no_price_history is labelled data_state live | backend/showme/server.py:1688-1693 (set), 1696-1714 (veto check); ui/src/functio |
| TLH |  | P1 | confirmed | Reports nothing to harvest while a loss position exists | ui/src/functions/portfolio/TaxLossHarvest.tsx:288 (nothing-to-harvest copy); bac |
| TRAN |  | P1 | confirmed | Press release shown as an earnings call transcript | backend/showme/engine/functions/news/tran.py:1-19 (docstring), 318-368 (_fetch_s |
| TRAN |  | P1 | confirmed | Speakers and roles invented by the parser | backend/showme/engine/functions/news/tran.py:449-495 (_parse_transcript_text; cu |
| TRDH |  | P1 | confirmed | TYO and HKEX open/close state wrong during lunch breaks and at TYO close | backend/showme/engine/reference/exchange_registry.py:58 (TYO 09:00-15:00), :60 ( |
| TRQA |  | P1 | confirmed | Q&A runs over the press release and returns unrelated passages as answers | backend/showme/engine/functions/news/trqa.py:1-18 (docstring), 157-160 (sec_8k_e |
| TSAR |  | P1 | confirmed | Inline speaker labels not split; CFO remarks attributed to the CEO | backend/showme/engine/functions/news/tsar.py:674-720 (_segment; inline speaker s |
| WACC |  | P1 | confirmed | Cost of debt uses an option-adjusted spread, not a yield | backend/showme/engine/functions/equity/wacc.py:203 (fred.series('BAMLC0A4CBBB')) |
| WACC |  | P1 | confirmed | Capital-structure weights are wrong for banks and financials | backend/showme/engine/functions/equity/wacc.py:251-263 (debt-zero-only sector de |
| WB |  | P1 | confirmed | as_of is stamped with the request date, not the observation date, so stale values read as current | backend/showme/engine/functions/bond/wb.py:59-64 (as_of = today for non-template |
| WCRS |  | P1 | confirmed | ECB daily fix is shown as a live quote (green live pill) | backend/showme/engine/functions/fx/_funcs.py:1076 and 652 (live_official); ui/sr |
| WCRS |  | P1 | confirmed | Spread (pips) is a constant 0.02 percent of the rate, not a market spread | backend/showme/engine/functions/fx/_funcs.py:272-273 (bid, ask) and 290 (spread_ |
| WEI |  | P1 | confirmed | World indices are labelled live and stamped with request time on a closed market | backend/showme/engine/functions/screen/_funcs.py:2331 (market_state default live |
| WHAL |  | P1 | confirmed | Equity 24h window drops the last session on non-trading days | backend/showme/engine/functions/misc/whal.py:359 (ranges = ['1d','5d'] for lookb |
| YAS |  | P1 | confirmed | Face value is not scaled against the per-100 price, so YTM is wrong when face is not 100 | backend/showme/engine/functions/bond/yas.py:218 (face read), 266 (price per 100) |

## Suggested repair order per category (D)

- **api**: ISIN(P0), BQL(P1), BQUANT(P1), DAPI(P2), FLDS(P2)
- **bond**: CRPR(P0), TAUC(P0), ALLQ(P1), SRSK(P1), WB(P1), YAS(P1), CRVF(P2), DDIS(P2), DEBT(P2), GC3D(P2)
- **chart**: GP(P1), HP(P1), TECH(P1), CHGS(P2)
- **comm**: MEET(P1), PEOP(P1)
- **commodity**: CPF(P0), WETR(P0), BGAS(P1), BOIL(P1), GLCO(P1), NGAS(P1)
- **derivative**: OMON(P1), GEX(P1), HVT(P1), IVOL(P1), OSA(P1), OVME(P3)
- **equity**: FA(P0), DARK(P0), DCF(P0), DPF(P0), FTS(P0), LITM(P0), DES(P1), ANR(P1), CACT(P1), DCFS(P1), DDM(P1), EE(P1), ESG(P1), FORM4(P1), HDS(P1), HFS(P1), RV(P1), WACC(P1), APPL(P2), BETA(P2), DVD(P2), EREV(P2), PIB(P2), SPLC(P2)
- **fx**: OVDV(P0), WCRS(P1), FRD(P2), FXFC(P2), FXH(P2), FXIP(P2)
- **macro**: COUN(P0), ECFC(P0), ECST(P0), ECO(P1), WIRP(P1), BTMM(P1), GMM(P1), REGM(P1), TRDH(P1), VCAP(P2)
- **misc**: SAT(P0), BIO(P1), CDE(P1), POLY(P1), WHAL(P1), ALRT(P2), BMC(P2), DINE(P2), FLY(P2), GRAB(P2), LANG(P2), ONCH(P2)
- **news**: TOP(P0), NSE(P0), TLDR(P0), CN(P1), AV(P1), BRIEF(P1), EVTS(P1), NALRT(P1), SOSC(P1), TRAN(P1), TRQA(P1), TSAR(P1), NI(P2), READ(P2)
- **portfolio**: ACCT(P0), BMTX(P0), CORR(P0), LOTS(P0), PORT_WHATIF(P0), PSC(P0), TRA(P0), BLAK(P1), MARS(P1), MGN(P1), MLSIG(P1), PFA(P1), PORT_OPT(P1), PVAR(P1), REBA(P1), RPAR(P1), STRS(P1), TLH(P1), PORT(P2), BTFW(P2), BTUNE(P2), GREEKS(P2), PCAS(P2)
- **screen**: MOST(P0), MAP(P1), CSRC(P1), FSRC(P1), MOSS(P1), WEI(P1), EQS(P2), FRH(P2), ICX(P2), MICRO(P2), SECF(P2), SECT(P2), SRCH(P2)
- **trade**: FXGO(P0), TCA(P0), TSOX(P0), AIM(P1), BBGT(P1), EMSX(P1), EXEC(P1)

## Every function

| Code | Category | B1 data | B2 reviewed | Recompute | Worst | Surviving findings |
|---|---|---|---|---|---|---:|
| FA | equity | AMBER | True | False | P0 | 7 |
| TOP | news | AMBER | True | None | P0 | 4 |
| ACCT | portfolio | AMBER | True | False | P0 | 4 |
| BMTX | portfolio | GREEN | True | None | P0 | 7 |
| CORR | portfolio | GREEN | True | False | P0 | 9 |
| COUN | macro | GREEN | True | False | P0 | 7 |
| CPF | commodity | GREEN | True | False | P0 | 9 |
| CRPR | bond | GREEN | True | False | P0 | 8 |
| DARK | equity | AMBER | True | False | P0 | 4 |
| DCF | equity | AMBER | True | True | P0 | 4 |
| DPF | equity | AMBER | True | False | P0 | 4 |
| ECFC | macro | GREEN | True | True | P0 | 3 |
| ECST | macro | GREEN | True | True | P0 | 5 |
| FTS | equity | GREEN | True | False | P0 | 6 |
| FXGO | trade | GREEN | True | False | P0 | 5 |
| ISIN | api | GREEN | True | True | P0 | 8 |
| LITM | equity | AMBER | True | False | P0 | 3 |
| LOTS | portfolio | AMBER | True | None | P0 | 6 |
| MOST | screen | AMBER | True | False | P0 | 5 |
| NSE | news | AMBER | True | False | P0 | 4 |
| OVDV | fx | GREEN | True | True | P0 | 5 |
| PORT_WHATIF | portfolio | GREEN | True | False | P0 | 7 |
| PSC | portfolio | GREEN | True | True | P0 | 4 |
| SAT | misc | GREEN | True | False | P0 | 6 |
| TAUC | bond | GREEN | True | False | P0 | 4 |
| TCA | trade | AMBER | True | False | P0 | 8 |
| TLDR | news | AMBER | True | False | P0 | 6 |
| TRA | portfolio | GREEN | True | False | P0 | 5 |
| TSOX | trade | GREEN | True | False | P0 | 4 |
| WETR | commodity | GREEN | True | False | P0 | 5 |
| CN | news | AMBER | True | False | P1 | 4 |
| DES | equity | GREEN | True | True | P1 | 4 |
| ECO | macro | GREEN | True | False | P1 | 7 |
| GP | chart | GREEN | True | False | P1 | 8 |
| HP | chart | GREEN | True | False | P1 | 5 |
| MAP | screen | GREEN | True | False | P1 | 3 |
| OMON | derivative | GREEN | True | False | P1 | 4 |
| WIRP | macro | GREEN | True | False | P1 | 6 |
| AIM | trade | AMBER | True | False | P1 | 4 |
| ALLQ | bond | AMBER | True | False | P1 | 7 |
| ANR | equity | GREEN | True | True | P1 | 6 |
| AV | news | AMBER | True | True | P1 | 7 |
| BBGT | trade | GREEN | True | False | P1 | 4 |
| BGAS | commodity | GREEN | True | False | P1 | 7 |
| BIO | misc | GREEN | True | False | P1 | 3 |
| BLAK | portfolio | GREEN | True | True | P1 | 7 |
| BOIL | commodity | GREEN | True | True | P1 | 6 |
| BQL | api | GREEN | True | False | P1 | 7 |
| BQUANT | api | GREEN | True | False | P1 | 2 |
| BRIEF | news | AMBER | True | True | P1 | 5 |
| BTMM | macro | GREEN | True | True | P1 | 4 |
| CACT | equity | GREEN | True | False | P1 | 6 |
| CDE | misc | AMBER | True | False | P1 | 4 |
| CSRC | screen | GREEN | True | False | P1 | 5 |
| DCFS | equity | GREEN | True | True | P1 | 6 |
| DDM | equity | AMBER | True | False | P1 | 5 |
| EE | equity | GREEN | True | True | P1 | 5 |
| EMSX | trade | GREEN | True | False | P1 | 4 |
| ESG | equity | GREEN | True | False | P1 | 6 |
| EVTS | news | GREEN | True | False | P1 | 4 |
| EXEC | trade | AMBER | True | False | P1 | 8 |
| FORM4 | equity | GREEN | True | False | P1 | 8 |
| FSRC | screen | GREEN | True | False | P1 | 3 |
| GEX | derivative | GREEN | True | False | P1 | 7 |
| GLCO | commodity | AMBER | True | True | P1 | 5 |
| GMM | macro | GREEN | True | False | P1 | 6 |
| HDS | equity | GREEN | True | False | P1 | 8 |
| HFS | equity | GREEN | True | False | P1 | 3 |
| HVT | derivative | GREEN | True | False | P1 | 1 |
| IVOL | derivative | GREEN | True | False | P1 | 4 |
| MARS | portfolio | AMBER | True | False | P1 | 7 |
| MEET | comm | GREEN | True | False | P1 | 10 |
| MGN | portfolio | AMBER | True | True | P1 | 6 |
| MLSIG | portfolio | AMBER | True | False | P1 | 7 |
| MOSS | screen | GREEN | True | False | P1 | 3 |
| NALRT | news | GREEN | True | True | P1 | 3 |
| NGAS | commodity | GREEN | True | False | P1 | 2 |
| OSA | derivative | GREEN | True | False | P1 | 3 |
| PEOP | comm | GREEN | True | False | P1 | 8 |
| PFA | portfolio | GREEN | True | True | P1 | 5 |
| POLY | misc | AMBER | True | False | P1 | 4 |
| PORT_OPT | portfolio | AMBER | True | False | P1 | 9 |
| PVAR | portfolio | AMBER | True | True | P1 | 6 |
| REBA | portfolio | GREEN | True | False | P1 | 5 |
| REGM | macro | GREEN | True | True | P1 | 4 |
| RPAR | portfolio | GREEN | True | False | P1 | 7 |
| RV | equity | AMBER | True | True | P1 | 5 |
| SOSC | news | AMBER | True | None | P1 | 5 |
| SRSK | bond | AMBER | True | True | P1 | 8 |
| STRS | portfolio | AMBER | True | False | P1 | 7 |
| TECH | chart | GREEN | True | False | P1 | 6 |
| TLH | portfolio | AMBER | True | True | P1 | 5 |
| TRAN | news | GREEN | True | False | P1 | 4 |
| TRDH | macro | GREEN | True | False | P1 | 4 |
| TRQA | news | GREEN | True | True | P1 | 2 |
| TSAR | news | AMBER | True | True | P1 | 3 |
| WACC | equity | GREEN | True | False | P1 | 6 |
| WB | bond | GREEN | True | False | P1 | 4 |
| WCRS | fx | GREEN | True | True | P1 | 4 |
| WEI | screen | GREEN | True | False | P1 | 3 |
| WHAL | misc | GREEN | True | False | P1 | 6 |
| YAS | bond | GREEN | True | True | P1 | 5 |
| CRVF | bond | GREEN | True | True | P2 | 5 |
| PORT | portfolio | AMBER | True | True | P2 | 6 |
| ALRT | misc | AMBER | True | None | P2 | 8 |
| APPL | equity | GREEN | True | None | P2 | 4 |
| BETA | equity | GREEN | True | True | P2 | 5 |
| BMC | misc | GREEN | True | None | P2 | 2 |
| BTFW | portfolio | GREEN | True | None | P2 | 5 |
| BTUNE | portfolio | GREEN | True | None | P2 | 4 |
| CHGS | chart | GREEN | True | True | P2 | 5 |
| DAPI | api | GREEN | True | True | P2 | 3 |
| DDIS | bond | AMBER | True | True | P2 | 2 |
| DEBT | bond | GREEN | True | True | P2 | 5 |
| DINE | misc | AMBER | True | True | P2 | 4 |
| DVD | equity | GREEN | True | True | P2 | 3 |
| EQS | screen | GREEN | True | True | P2 | 3 |
| EREV | equity | AMBER | True | True | P2 | 4 |
| FLDS | api | GREEN | True | False | P2 | 4 |
| FLY | misc | GREEN | True | True | P2 | 6 |
| FRD | fx | GREEN | True | True | P2 | 4 |
| FRH | screen | GREEN | True | True | P2 | 3 |
| FXFC | fx | GREEN | True | True | P2 | 4 |
| FXH | fx | GREEN | True | True | P2 | 6 |
| FXIP | fx | GREEN | True | True | P2 | 3 |
| GC3D | bond | GREEN | True | True | P2 | 4 |
| GRAB | misc | GREEN | True | None | P2 | 3 |
| GREEKS | portfolio | GREEN | True | True | P2 | 4 |
| ICX | screen | GREEN | True | False | P2 | 3 |
| LANG | misc | GREEN | True | False | P2 | 3 |
| MICRO | screen | AMBER | True | True | P2 | 2 |
| NI | news | AMBER | True | False | P2 | 4 |
| ONCH | misc | GREEN | True | True | P2 | 3 |
| PCAS | portfolio | AMBER | True | False | P2 | 5 |
| PIB | equity | GREEN | True | True | P2 | 3 |
| READ | news | AMBER | True | True | P2 | 3 |
| SECF | screen | GREEN | True | True | P2 | 3 |
| SECT | screen | AMBER | True | True | P2 | 3 |
| SPLC | equity | GREEN | True | False | P2 | 3 |
| SRCH | screen | AMBER | True | True | P2 | 4 |
| VCAP | macro | GREEN | True | True | P2 | 1 |
| OVME | derivative | GREEN | True | True | P3 | 2 |

## Blind spots (completeness critic)

- **Unverified high-severity findings in functions with check=false** — Many P0/P1 findings sit in functions with no numeric recomputation, including CRPR (2xP0), SAT (2xP0), FTS (2xP0), CPF, WETR, TLDR, ACCT, TRA, MOST, TSOX, CORR, DARK, DPF, LITM, COUN, NSE, TCA, EXEC and FXGO. Their severities are unconfirmed, so the highest-risk items may be false positives or understated. → Require a reproducible test or independent recomputation for every P0/P1 with check=false, starting with the P0 list, before trusting the severity ranking.
- **Functions with check=null** — APPL, ALRT, BMC, GRAB, SOSC, TOP, BMTX, BTFW, BTUNE and LOTS have no numeric check at all. TOP (P0), BMTX (P0) and LOTS (P0) are among them, so these were effectively reviewed by reading only. → Decide whether each one has numeric output. If it does, run the recomputation; if it does not, record that explicitly as non-numeric so the gap is visible.
- **Intraday timing, as-of dates and market calendars** — A static review and a numeric recomputation both use a fixed snapshot. They cannot see stale quotes, mixed as-of timestamps across fields, time zone or session-close mismatches, holiday calendars, or ex-dividend and settlement date logic. This matters for GEX, OMON, IVOL, FXH, FX and bond functions. → Replay each numeric function against timestamped snapshots taken at different times of day, with mixed as-of inputs and a holiday or half-day calendar, and assert that outputs carry the correct as-of time.
- **Provider outages, empty and partial responses** — The review inspects code paths but does not inject failures. Empty arrays, 429 or timeout responses, partial field sets and null vendor values are the usual source of silent wrong numbers or crashes in terminal functions such as DAPI, FLDS, BQL and the bulk price-history paths. → Add fault-injection tests with empty, null, truncated, rate-limited and timed-out provider responses for each data-fetching function, and check that each one degrades visibly rather than returning plausible values.
- **Locale and number/date parsing** — The workspace sits under a Turkish-locale Windows profile (Kullanıcı). Decimal comma versus dot, thousands separators, dd.mm versus mm/dd dates and Turkish-dotted-I case folding can all corrupt parsed numbers or tickers without any calculation error that a formula recomputation would catch. → Run parsing and formatting tests under tr-TR and en-US inputs, including negative numbers, percentages, dates and tickers containing I or ı, and compare parsed values to expected values.
- **UI-only defects and rendering** — Findings on tables, sorting, truncation, chart axes, label overlap, responsive layout and stale state after a refresh are invisible to code reading and to numeric checks. → Render each screen with representative data (empty, one row, very large values, negatives) at desktop and phone widths, capture screenshots, and check console errors on each one.
- **Cross-function consistency on shared inputs** — Functions that share inputs can disagree while each looks correct alone: DCF, DCFS and WACC; PORT, PORT_OPT and PORT_WHATIF; GREEKS, OVME and OVDV; and CRVF, DDIS and DEBT. The review was per function, so these mismatches were not checked. → Build a consistency matrix of shared inputs and outputs (for example, the same WACC or the same option price fed through each function) and assert equality or documented differences.
- **Coverage depth behind reviewed=true** — reviewed=true only says a function was read. It does not show branch coverage, error paths, or the edge cases that matter in financial code, such as zero or negative denominators, division by zero in ratios, and sign flips in P&L or greeks. → Measure branch coverage for each function and add targeted tests for zero, negative, NaN and extreme inputs, then confirm that each surviving finding is backed by a test or repro.
- **Fix regressions and secrets/security** — Findings reported so far are not shown to have been fixed or re-verified, and the review did not state whether it searched for hardcoded API keys, eval or unsafe string-built requests, or unescaped output. → After fixes, re-run the failing checks to confirm them, and run a secrets and injection scan (keys in source, eval, unvalidated query parameters) across the repository.
