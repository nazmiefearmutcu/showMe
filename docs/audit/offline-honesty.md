# Offline honesty audit (T10)

Generated: 2026-11-08T02:10:44.529485+00:00 - every outbound connection refused, budget 8s per call. Network-cut probe: urllib=refused (URLError), requests=refused (ProxyError), httpx=refused (ConnectError), curl_cffi=refused (ConnectionError), aiohttp=refused (ClientConnectorError), yfinance=refused (empty)

- Functions called: 142; with a red finding: 21; with any finding: 21

| Code | Case | HTTP | status | data_state | s | Findings |
|---|---|---:|---|---|---:|---|
| ACCT | default | 200 | empty | reference | 0.0 | clean |
| AIM | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| ALLQ | default | 200 | provider_unavailable | provider_unavailable | 0.3 | clean |
| ALLQ | US10Y | 200 | provider_unavailable | provider_unavailable | 0.03 | clean |
| ALRT | default | 200 | ok | reference | 0.0 | clean |
| ANR | default | 200 | provider_unavailable | provider_unavailable | 6.4 | clean |
| ANR | AAPL | 200 | ok | reference | 5.02 | clean |
| APPL | default | 200 | provider_unavailable | model | 3.02 | clean |
| APPL | AAPL | 200 | provider_unavailable | model | 3.01 | clean |
| AV | default | 200 | provider_unavailable | provider_unavailable | 0.21 | clean |
| BBGT | default | 200 | input_error | model | 5.55 | clean |
| BETA | default | 200 | provider_unavailable | synthetic | 3.28 | clean |
| BETA | AAPL | 200 | provider_unavailable | synthetic | 3.39 | clean |
| BGAS | default | 200 | provider_unavailable | provider_unavailable | 4.41 | clean |
| BGAS | CL=F | 200 | provider_unavailable | provider_unavailable | 4.47 | clean |
| BIO | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['macos_local_auth_bridge']) |
| BLAK | default | 200 | ok | synthetic | 7.47 | T2:fake_source (red) source 'synthetic_fallback' is sample/demo data |
| BMC | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['showme_curriculum']) |
| BMTX | default | 200 | provider_unavailable | - | 8.11 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| BOIL | default | 200 | provider_unavailable | provider_unavailable | 7.76 | clean |
| BOIL | CL=F | 200 | provider_unavailable | provider_unavailable | 6.52 | clean |
| BQL | default | 200 | provider_unavailable | provider_unavailable | 4.04 | clean |
| BQUANT | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['local_notebook_manifest']) |
| BRIEF | default | 200 | provider_unavailable | - | 1.01 | clean |
| BTFW | default | 200 | provider_unavailable | - | 8.09 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| BTFW | AAPL | 200 | ok | synthetic | 6.63 | clean |
| BTMM | default | 200 | ok | live | 0.1 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['local fallback']) |
| BTUNE | default | 200 | ok | synthetic | 4.18 | clean |
| BTUNE | AAPL | 200 | ok | synthetic | 3.8 | clean |
| CACT | default | 200 | provider_unavailable | provider_unavailable | 3.16 | clean |
| CACT | AAPL | 200 | provider_unavailable | provider_unavailable | 3.02 | clean |
| CDE | default | 200 | ok | reference | 0.0 | clean |
| CHGS | default | 200 | empty | live | 2.18 | clean |
| CHGS | AAPL | 200 | empty | live | 2.16 | clean |
| CN | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| CN | AAPL | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| CORR | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| COUN | default | 200 | ok | reference | 0.4 | clean |
| CPF | default | 200 | provider_unavailable | provider_unavailable | 5.45 | clean |
| CPF | CL=F | 200 | provider_unavailable | provider_unavailable | 4.89 | clean |
| CRPR | default | 200 | ok | reference | 0.0 | clean |
| CRPR | US10Y | 200 | ok | reference | 0.0 | clean |
| CRVF | default | 200 | ok | model | 0.33 | clean |
| CSRC | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| CSRC | CL=F | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| DAPI | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['showme_fastapi_routes_curated']) |
| DARK | default | 200 | provider_unavailable | provider_unavailable | 2.53 | clean |
| DARK | AAPL | 200 | provider_unavailable | provider_unavailable | 2.04 | clean |
| DCF | default | 200 | input_error | synthetic | 6.69 | clean |
| DCF | AAPL | 200 | input_error | synthetic | 4.68 | clean |
| DCFS | default | 200 | input_error | synthetic | 7.22 | clean |
| DCFS | AAPL | 200 | input_error | synthetic | 7.67 | clean |
| DDIS | default | 200 | empty | reference | 0.0 | clean |
| DDIS | AAPL | 200 | provider_unavailable | provider_unavailable | 0.01 | clean |
| DDM | default | 200 | ok | live | 0.46 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['yfinance']) |
| DDM | AAPL | 200 | ok | live | 0.49 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['yfinance']) |
| DEBT | default | 200 | provider_unavailable | provider_unavailable | 0.09 | clean |
| DES | default | 200 | ok | live | 2.52 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['yfinance']) |
| DES | AAPL | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['yfinance']) |
| DINE | default | 200 | provider_unavailable | provider_unavailable | 0.24 | clean |
| DPF | default | 200 | provider_unavailable | model | 0.0 | clean |
| DPF | AAPL | 200 | provider_unavailable | model | 0.0 | clean |
| DVD | default | 200 | provider_unavailable | provider_unavailable | 2.05 | clean |
| DVD | AAPL | 200 | provider_unavailable | provider_unavailable | 2.04 | clean |
| ECFC | default | 200 | provider_unavailable | reference | 0.07 | clean |
| ECO | default | 200 | provider_unavailable | synthetic | 0.01 | clean |
| ECST | default | 200 | ok | synthetic | 0.05 | clean |
| EE | default | 200 | provider_unavailable | model | 2.02 | clean |
| EE | AAPL | 200 | provider_unavailable | model | 2.04 | clean |
| EMSX | default | 200 | input_error | model | 0.02 | clean |
| EQS | default | 200 | ok | model | 0.01 | clean |
| EQS | AAPL | 200 | ok | model | 0.01 | clean |
| EREV | default | 200 | provider_unavailable | synthetic | 0.0 | clean |
| EREV | AAPL | 200 | provider_unavailable | synthetic | 1.0 | clean |
| ESG | default | 200 | provider_unavailable | provider_unavailable | 2.06 | clean |
| ESG | AAPL | 200 | provider_unavailable | provider_unavailable | 2.05 | clean |
| EVTS | default | 200 | provider_unavailable | provider_unavailable | 2.04 | clean |
| EVTS | AAPL | 200 | provider_unavailable | provider_unavailable | 2.04 | clean |
| EXEC | default | 200 | empty | live | 0.04 | clean |
| FA | default | 200 | provider_unavailable | synthetic | 3.01 | clean |
| FA | AAPL | 200 | provider_unavailable | synthetic | 3.02 | clean |
| FLDS | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['showme_field_catalog']) |
| FLY | default | 200 | provider_unavailable | synthetic | 0.11 | clean |
| FORM4 | default | 200 | provider_unavailable | model | 2.12 | clean |
| FORM4 | AAPL | 200 | provider_unavailable | model | 2.03 | clean |
| FRD | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| FRD | EURUSD | 200 | provider_unavailable | - | 8.0 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| FRH | default | 200 | provider_unavailable | provider_unavailable | 0.91 | clean |
| FSRC | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| FSRC | SPY | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| FTS | default | 200 | provider_unavailable | reference | 0.14 | clean |
| FTS | AAPL | 200 | provider_unavailable | reference | 0.01 | clean |
| FXFC | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| FXFC | EURUSD | 200 | ok | reference | 2.47 | clean |
| FXGO | default | 200 | provider_unavailable | provider_unavailable | 0.01 | clean |
| FXGO | EURUSD | 200 | provider_unavailable | provider_unavailable | 0.01 | clean |
| FXH | default | 200 | provider_unavailable | live | 2.07 | clean |
| FXH | EURUSD | 200 | provider_unavailable | live | 2.06 | clean |
| FXIP | default | 200 | ok | reference | 4.42 | clean |
| FXIP | EURUSD | 200 | ok | reference | 4.4 | clean |
| GC3D | default | 200 | ok | model | 0.17 | clean |
| GEX | default | 200 | ok | model | 2.65 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| GEX | AAPL | 200 | ok | model | 2.3 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| GLCO | default | 200 | provider_unavailable | reference | 3.64 | clean |
| GLCO | CL=F | 200 | provider_unavailable | reference | 6.46 | clean |
| GMM | default | 200 | provider_unavailable | provider_unavailable | 0.06 | clean |
| GP | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| GRAB | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['local_capture_plan']) |
| GREEKS | default | 200 | ok | model | 0.02 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| HDS | default | 200 | ok | reference | 2.08 | clean |
| HDS | AAPL | 200 | ok | reference | 2.04 | clean |
| HFS | default | 200 | ok | live | 0.0 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['sec_13f']) |
| HFS | AAPL | 200 | ok | live | 0.01 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['sec_13f']) |
| HP | default | 200 | ok | reference | 4.28 | clean |
| HVT | default | 200 | provider_unavailable | synthetic | 2.9 | clean |
| HVT | AAPL | 200 | provider_unavailable | synthetic | 2.44 | clean |
| ICX | default | 200 | empty | reference | 8.04 | clean |
| ICX | AAPL | 200 | empty | reference | 0.2 | clean |
| ISIN | default | 200 | empty | live | 0.12 | clean |
| IVOL | default | 200 | provider_unavailable | reference | 4.46 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| IVOL | AAPL | 200 | provider_unavailable | reference | 4.29 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| LANG | default | 200 | ok | live | 0.01 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['showme_i18n_registry']) |
| LITM | default | 200 | empty | live | 2.03 | clean |
| LITM | AAPL | 200 | empty | live | 2.05 | clean |
| LOTS | default | 200 | empty | live | 0.02 | clean |
| MAP | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| MARS | default | 200 | provider_unavailable | model | 6.26 | clean |
| MEET | default | 200 | provider_unavailable | synthetic | 1.12 | clean |
| MGN | default | 200 | empty | reference | 0.0 | clean |
| MICRO | default | 200 | provider_unavailable | - | 8.02 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| MICRO | BTCUSDT | 200 | provider_unavailable | - | 8.0 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| MLSIG | default | 200 | provider_unavailable | model | 3.03 | clean |
| MLSIG | AAPL | 200 | provider_unavailable | model | 3.02 | clean |
| MOSS | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| MOST | default | 200 | provider_unavailable | - | 1.01 | clean |
| NALRT | default | 200 | ok | reference | 0.4 | clean |
| NALRT | AAPL | 200 | ok | reference | 3.36 | clean |
| NGAS | default | 200 | provider_unavailable | provider_unavailable | 4.51 | clean |
| NGAS | CL=F | 200 | provider_unavailable | provider_unavailable | 4.41 | clean |
| NI | default | 200 | empty | live | 0.93 | clean |
| NSE | default | 200 | provider_unavailable | reference | 0.47 | clean |
| OMON | default | 200 | provider_unavailable | provider_unavailable | 2.03 | clean |
| OMON | AAPL | 200 | provider_unavailable | provider_unavailable | 2.03 | clean |
| ONCH | default | 200 | provider_unavailable | provider_unavailable | 0.06 | clean |
| ONCH | BTCUSDT | 200 | provider_unavailable | provider_unavailable | 0.16 | clean |
| OSA | default | 200 | ok | model | 0.01 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| OVDV | default | 200 | ok | live | 2.32 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['model:fx_vol_smile']) |
| OVDV | EURUSD | 200 | ok | live | 2.34 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['model:fx_vol_smile']) |
| OVME | default | 200 | ok | model | 0.01 | T4:placeholder_value (red) spot=100.0 looks like a demo price the request did not supply |
| PCAS | default | 200 | empty | reference | 0.0 | clean |
| PEOP | default | 200 | provider_unavailable | reference | 0.15 | clean |
| PFA | default | 200 | ok | model | 0.0 | clean |
| PIB | default | 200 | provider_unavailable | model | 0.01 | clean |
| PIB | AAPL | 200 | provider_unavailable | model | 0.13 | clean |
| POLY | default | 200 | provider_unavailable | provider_unavailable | 0.23 | clean |
| PORT | default | 200 | empty | reference | 0.0 | clean |
| PORT_OPT | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| PORT_WHATIF | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| PSC | default | 200 | input_error | reference | 4.46 | clean |
| PVAR | default | 200 | empty | reference | 0.0 | clean |
| READ | default | 200 | empty | live | 0.04 | clean |
| REBA | default | 200 | ok | model | 0.0 | clean |
| REGM | default | 200 | provider_unavailable | provider_unavailable | 3.04 | clean |
| RPAR | default | 200 | provider_unavailable | model | 7.62 | clean |
| RV | default | 200 | ok | live | 3.01 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['finnhub', 'yfinance']) |
| RV | AAPL | 200 | ok | live | 3.01 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['finnhub', 'yfinance']) |
| SAT | default | 200 | provider_unavailable | provider_unavailable | 0.03 | clean |
| SECF | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| SECT | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| SOSC | default | 200 | provider_unavailable | reference | 0.54 | clean |
| SOSC | AAPL | 200 | provider_unavailable | reference | 0.53 | clean |
| SPLC | default | 200 | ok | reference | 0.02 | clean |
| SPLC | AAPL | 200 | ok | reference | 0.14 | clean |
| SRCH | default | 200 | provider_unavailable | - | 8.0 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| SRCH | US10Y | 200 | provider_unavailable | - | 8.02 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| SRSK | default | 200 | provider_unavailable | provider_unavailable | 1.04 | clean |
| STRS | default | 200 | empty | reference | 0.0 | clean |
| TAUC | default | 200 | provider_unavailable | synthetic | 0.25 | clean |
| TAUC | US10Y | 200 | provider_unavailable | synthetic | 0.28 | clean |
| TCA | default | 200 | empty | reference | 0.03 | clean |
| TECH | default | 200 | empty | live | 2.21 | clean |
| TECH | AAPL | 200 | empty | live | 2.15 | clean |
| TLDR | default | 200 | provider_unavailable | provider_unavailable | 0.59 | clean |
| TLH | default | 200 | empty | reference | 0.0 | clean |
| TOP | default | 200 | empty | reference | 0.38 | clean |
| TRA | default | 200 | provider_unavailable | synthetic | 2.26 | clean |
| TRAN | default | 200 | provider_unavailable | provider_unavailable | 0.05 | clean |
| TRAN | AAPL | 200 | provider_unavailable | provider_unavailable | 0.03 | clean |
| TRDH | default | 200 | ok | live | 1.59 | T10:offline_live_claim (red) data_state=live with every connection refused (sources=['exchange_calendars']) |
| TRQA | default | 200 | provider_unavailable | reference | 0.01 | clean |
| TRQA | AAPL | 200 | provider_unavailable | reference | 0.02 | clean |
| TSAR | default | 200 | provider_unavailable | provider_unavailable | 0.04 | clean |
| TSOX | default | 200 | input_error | model | 0.0 | clean |
| TSOX | US10Y | 200 | input_error | model | 0.0 | clean |
| VCAP | default | 200 | ok | reference | 0.33 | clean |
| WACC | default | 200 | ok | synthetic | 2.05 | T2:fake_source (red) source 'synthetic_beta' is sample/demo data |
| WACC | AAPL | 200 | ok | synthetic | 2.04 | T2:fake_source (red) source 'synthetic_beta' is sample/demo data |
| WB | default | 200 | ok | model | 0.56 | clean |
| WCRS | default | 200 | ok | reference | 2.6 | clean |
| WEI | default | 200 | provider_unavailable | - | 8.01 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| WETR | default | 200 | provider_unavailable | model | 0.1 | clean |
| WETR | CL=F | 200 | provider_unavailable | model | 0.01 | clean |
| WHAL | default | 200 | provider_unavailable | provider_unavailable | 0.61 | clean |
| WHAL | BTCUSDT | 200 | provider_unavailable | provider_unavailable | 0.4 | clean |
| WIRP | default | 200 | provider_unavailable | - | 8.02 | T10:offline_timeout (amber) hit the server timeout with the network cut instead of failing fast |
| YAS | default | 200 | provider_unavailable | reference | 0.01 | clean |
| YAS | US10Y | 200 | provider_unavailable | reference | 0.01 | clean |
