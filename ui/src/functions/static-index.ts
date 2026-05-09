import type { FunctionEntry } from "@/lib/sidecar";

export const STATIC_FUNCTION_INDEX: FunctionEntry[] = [
  {
    "code": "ACCT",
    "name": "Multi-Account Aggregation",
    "category": "portfolio",
    "description": "Per-account position roll-up + cross-account exposure totals."
  },
  {
    "code": "AIM",
    "name": "Order Management",
    "category": "trade",
    "description": ""
  },
  {
    "code": "ALLQ",
    "name": "Dealer Quotes (TRACE proxy)",
    "category": "bond",
    "description": ""
  },
  {
    "code": "ALRT",
    "name": "Alerts",
    "category": "misc",
    "description": ""
  },
  {
    "code": "ANR",
    "name": "Analyst Recommendations",
    "category": "equity",
    "description": "Strong Buy/Buy/Hold/Sell/Strong Sell dağılımı + 12-ay fiyat hedefi (mean/median/min/max)."
  },
  {
    "code": "APPL",
    "name": "Industry Taxonomy",
    "category": "equity",
    "description": ""
  },
  {
    "code": "AV",
    "name": "Audio/Video Archive",
    "category": "news",
    "description": ""
  },
  {
    "code": "BBGT",
    "name": "Multi-Asset Trade Ticket",
    "category": "trade",
    "description": ""
  },
  {
    "code": "BETA",
    "name": "CAPM Beta",
    "category": "equity",
    "description": "Hedef vs benchmark β = cov(r_i, r_m) / var(r_m). Çoklu pencere ve benchmark."
  },
  {
    "code": "BGAS",
    "name": "Natural Gas Spot",
    "category": "commodity",
    "description": ""
  },
  {
    "code": "BIO",
    "name": "Biometric Auth",
    "category": "misc",
    "description": ""
  },
  {
    "code": "BLAK",
    "name": "Black-Litterman",
    "category": "portfolio",
    "description": "Posterior expected returns combining market prior with views."
  },
  {
    "code": "BMC",
    "name": "Market Concepts Education",
    "category": "misc",
    "description": ""
  },
  {
    "code": "BMTX",
    "name": "Backtest Matrix",
    "category": "portfolio",
    "description": "Run multiple strategies across a symbol universe in parallel."
  },
  {
    "code": "BOIL",
    "name": "Oil Spot",
    "category": "commodity",
    "description": ""
  },
  {
    "code": "BQL",
    "name": "ShowMe Query Language",
    "category": "api",
    "description": ""
  },
  {
    "code": "BQUANT",
    "name": "BQuant Notebook",
    "category": "api",
    "description": ""
  },
  {
    "code": "BRIEF",
    "name": "Daily Brief",
    "category": "news",
    "description": ""
  },
  {
    "code": "BTFW",
    "name": "Walk-Forward Backtest",
    "category": "portfolio",
    "description": "Run a registered strategy on historical OHLCV; equity curve + Sharpe + drawdown."
  },
  {
    "code": "BTMM",
    "name": "Country Rate Environment",
    "category": "macro",
    "description": "Central-bank policy-rate matrix from BIS CBPOL: latest rate, last move, 3M trend, country and region filters."
  },
  {
    "code": "BTUNE",
    "name": "Backtest Auto-Tuner",
    "category": "portfolio",
    "description": "Hyperparameter sweep over a strategy grid; rank by Sharpe / total return / Calmar."
  },
  {
    "code": "CACT",
    "name": "Corporate Actions",
    "category": "equity",
    "description": ""
  },
  {
    "code": "CDE",
    "name": "Custom Data Fields",
    "category": "misc",
    "description": ""
  },
  {
    "code": "CHGS",
    "name": "Chart Studies",
    "category": "chart",
    "description": ""
  },
  {
    "code": "CN",
    "name": "Company News",
    "category": "news",
    "description": ""
  },
  {
    "code": "CORR",
    "name": "Correlation Matrix",
    "category": "portfolio",
    "description": "Pearson + Spearman + downside correlation for a symbol set."
  },
  {
    "code": "COUN",
    "name": "Country Guide",
    "category": "macro",
    "description": ""
  },
  {
    "code": "CPF",
    "name": "Commodity Price Forecasts",
    "category": "commodity",
    "description": ""
  },
  {
    "code": "CRPR",
    "name": "Credit Rating Profile",
    "category": "bond",
    "description": ""
  },
  {
    "code": "CRVF",
    "name": "Yield Curve",
    "category": "bond",
    "description": ""
  },
  {
    "code": "CSRC",
    "name": "Commodity Screener",
    "category": "screen",
    "description": ""
  },
  {
    "code": "DAPI",
    "name": "ShowMe Data API",
    "category": "api",
    "description": ""
  },
  {
    "code": "DARK",
    "name": "Dark Pool Volume",
    "category": "equity",
    "description": "FINRA ATS (Alternative Trading System) weekly off-exchange volume by venue."
  },
  {
    "code": "DCF",
    "name": "Discounted Cash Flow",
    "category": "equity",
    "description": ""
  },
  {
    "code": "DCFS",
    "name": "DCF Sensitivity",
    "category": "equity",
    "description": "WACC × terminal-growth grid + ±20% input tornado."
  },
  {
    "code": "DDIS",
    "name": "Debt Distribution by Maturity",
    "category": "bond",
    "description": ""
  },
  {
    "code": "DDM",
    "name": "Dividend Discount Model",
    "category": "equity",
    "description": ""
  },
  {
    "code": "DEBT",
    "name": "Sovereign Debt Exposure",
    "category": "bond",
    "description": ""
  },
  {
    "code": "DES",
    "name": "Description",
    "category": "equity",
    "description": "Şirket özeti — sektör, market cap, çalışan sayısı, IPO tarihi, kısa açıklama."
  },
  {
    "code": "DINE",
    "name": "Restaurants",
    "category": "misc",
    "description": ""
  },
  {
    "code": "DPF",
    "name": "Dark Pool / ATS Volume",
    "category": "equity",
    "description": "FINRA-reported off-exchange (ATS) volume + dark-pool % of total."
  },
  {
    "code": "DVD",
    "name": "Dividends & Splits",
    "category": "equity",
    "description": ""
  },
  {
    "code": "ECFC",
    "name": "Economic Forecasts",
    "category": "macro",
    "description": ""
  },
  {
    "code": "ECO",
    "name": "Economic Calendar",
    "category": "macro",
    "description": ""
  },
  {
    "code": "ECST",
    "name": "Economic Statistics",
    "category": "macro",
    "description": ""
  },
  {
    "code": "EE",
    "name": "Earnings & Estimates",
    "category": "equity",
    "description": "Geçmiş kazançlar (actual vs consensus) + sürpriz % + sonraki tahmin tarihi."
  },
  {
    "code": "EMSX",
    "name": "Execution Management",
    "category": "trade",
    "description": ""
  },
  {
    "code": "EQS",
    "name": "Equity Screener",
    "category": "screen",
    "description": "DSL-based equity screener. Örnek: marketCap > 1000000000 AND pe < 15 AND sector = \"Technology\""
  },
  {
    "code": "EREV",
    "name": "Earnings Revisions",
    "category": "equity",
    "description": "Analyst recommendation buckets month-over-month + revision velocity."
  },
  {
    "code": "ESG",
    "name": "ESG Scores",
    "category": "equity",
    "description": ""
  },
  {
    "code": "EVTS",
    "name": "Corporate Events",
    "category": "news",
    "description": ""
  },
  {
    "code": "EXEC",
    "name": "Execution Monitor",
    "category": "trade",
    "description": "Live VWAP/TWAP slice-by-slice fill quality + pace tracking."
  },
  {
    "code": "FA",
    "name": "Financial Analysis",
    "category": "equity",
    "description": "Income statement + balance sheet + cash flow, son 5 yıl trendi."
  },
  {
    "code": "FLDS",
    "name": "Field Lookup",
    "category": "api",
    "description": ""
  },
  {
    "code": "FLY",
    "name": "Flight Tracking",
    "category": "misc",
    "description": ""
  },
  {
    "code": "FORM4",
    "name": "Insider Transactions",
    "category": "equity",
    "description": "Recent SEC Form 4 (insider) filings for the given ticker."
  },
  {
    "code": "FRD",
    "name": "FX Forward Rates",
    "category": "fx",
    "description": ""
  },
  {
    "code": "FRH",
    "name": "Funding Rate Heatmap",
    "category": "screen",
    "description": "Perpetual funding rates across Binance / Bybit / OKX (top 25 pairs)."
  },
  {
    "code": "FSRC",
    "name": "Fund Screener",
    "category": "screen",
    "description": ""
  },
  {
    "code": "FTS",
    "name": "SEC Full-Text Search",
    "category": "equity",
    "description": "Search SEC EDGAR filings by free text + form type + date range."
  },
  {
    "code": "FXFC",
    "name": "FX Forecasts",
    "category": "fx",
    "description": ""
  },
  {
    "code": "FXGO",
    "name": "FX Trading",
    "category": "trade",
    "description": ""
  },
  {
    "code": "FXH",
    "name": "FX Hedge",
    "category": "fx",
    "description": "Forward-rate overlay calculator for foreign-currency exposure."
  },
  {
    "code": "FXIP",
    "name": "FX Information Portal",
    "category": "fx",
    "description": ""
  },
  {
    "code": "GC3D",
    "name": "Yield Curve 3D (live FRED)",
    "category": "bond",
    "description": ""
  },
  {
    "code": "GEX",
    "name": "Gamma Exposure",
    "category": "derivative",
    "description": "Per-strike dealer gamma exposure + flip + walls."
  },
  {
    "code": "GLCO",
    "name": "Global Commodity Movers",
    "category": "commodity",
    "description": ""
  },
  {
    "code": "GMM",
    "name": "Global Macro Movers",
    "category": "macro",
    "description": ""
  },
  {
    "code": "GP",
    "name": "Price Graph",
    "category": "chart",
    "description": "Candlestick price history alias backed by ShowMe OHLCV adapters."
  },
  {
    "code": "GRAB",
    "name": "Screenshot Email",
    "category": "misc",
    "description": ""
  },
  {
    "code": "GREEKS",
    "name": "Portfolio Greeks",
    "category": "portfolio",
    "description": "Sum delta/gamma/vega/theta/rho across an option book."
  },
  {
    "code": "HDS",
    "name": "Holders",
    "category": "equity",
    "description": ""
  },
  {
    "code": "HFS",
    "name": "Holder Search",
    "category": "equity",
    "description": "13F reverse lookup — list filers holding a given issuer / CUSIP."
  },
  {
    "code": "HP",
    "name": "Historical Price",
    "category": "chart",
    "description": "Historical OHLCV table alias backed by ShowMe OHLCV adapters."
  },
  {
    "code": "HVT",
    "name": "Historical Volatility Trends",
    "category": "derivative",
    "description": ""
  },
  {
    "code": "ICX",
    "name": "Index Constituents",
    "category": "screen",
    "description": "Major equity index constituents (Wikipedia-backed cache)."
  },
  {
    "code": "ISIN",
    "name": "Symbol Cross-Reference",
    "category": "api",
    "description": "Resolve ISIN/CUSIP/SEDOL/Ticker → OpenFIGI canonical record + cross IDs."
  },
  {
    "code": "IVOL",
    "name": "Implied Vol Surface",
    "category": "derivative",
    "description": ""
  },
  {
    "code": "LANG",
    "name": "Language Switch",
    "category": "misc",
    "description": ""
  },
  {
    "code": "LITM",
    "name": "Litigation Monitor",
    "category": "equity",
    "description": "Recent 8-K Item 1.03/1.04/3.03 filings — bankruptcy, mine safety, security holder rights."
  },
  {
    "code": "LOTS",
    "name": "Tax Lots",
    "category": "portfolio",
    "description": "Open / list / sell tax lots with FIFO/LIFO/HIFO/specific-id selection."
  },
  {
    "code": "MAP",
    "name": "World Market Heatmap",
    "category": "screen",
    "description": "MSCI single-country ETF day-change heatmap (25+ countries)."
  },
  {
    "code": "MARS",
    "name": "Multi-Asset Risk",
    "category": "portfolio",
    "description": ""
  },
  {
    "code": "MEET",
    "name": "Meeting Briefing",
    "category": "comm",
    "description": "Pre-meeting briefing — Notion + Granola + portfolio + news + DES."
  },
  {
    "code": "MGN",
    "name": "Cross-Account Margin",
    "category": "portfolio",
    "description": "Margin requirements + buying power per account."
  },
  {
    "code": "MICRO",
    "name": "Market Microstructure",
    "category": "screen",
    "description": "Order-book depth, imbalance, spread and Kyle's lambda proxy."
  },
  {
    "code": "MLSIG",
    "name": "ML Signal Classifier",
    "category": "portfolio",
    "description": "Train a classifier on technical features → predict next N-day direction."
  },
  {
    "code": "MOSS",
    "name": "Most Volatile",
    "category": "screen",
    "description": "Realised volatility leaderboard across watchlist or universe."
  },
  {
    "code": "MOST",
    "name": "Most Active",
    "category": "screen",
    "description": ""
  },
  {
    "code": "NGAS",
    "name": "Natural Gas",
    "category": "commodity",
    "description": ""
  },
  {
    "code": "NI",
    "name": "News by Topic",
    "category": "news",
    "description": ""
  },
  {
    "code": "NALRT",
    "name": "Critical News Alerts",
    "category": "news",
    "description": "Ranks live headlines by market impact and raises critical/high news alerts."
  },
  {
    "code": "NSE",
    "name": "News Search Engine",
    "category": "news",
    "description": ""
  },
  {
    "code": "OMON",
    "name": "Option Monitor",
    "category": "derivative",
    "description": ""
  },
  {
    "code": "ONCH",
    "name": "On-Chain Metrics",
    "category": "misc",
    "description": "Crypto on-chain: fees, hash rate, active addresses, gas, mempool."
  },
  {
    "code": "OSA",
    "name": "Option Strategy Analysis",
    "category": "derivative",
    "description": ""
  },
  {
    "code": "OVDV",
    "name": "FX Option Volatility Surface",
    "category": "fx",
    "description": ""
  },
  {
    "code": "OVME",
    "name": "Option Valuation",
    "category": "derivative",
    "description": ""
  },
  {
    "code": "PCAS",
    "name": "PCA Factor Stress",
    "category": "portfolio",
    "description": "Apply k-σ shock along principal components (correlated stress)."
  },
  {
    "code": "PEOP",
    "name": "People Search",
    "category": "comm",
    "description": "Search executives, analysts, and contacts (local directory)."
  },
  {
    "code": "PFA",
    "name": "Performance Attribution (Brinson)",
    "category": "portfolio",
    "description": "Brinson-Hood-Beebower attribution by sector — allocation + selection + interaction."
  },
  {
    "code": "PIB",
    "name": "Public Information Book",
    "category": "equity",
    "description": ""
  },
  {
    "code": "POLY",
    "name": "Polymarket",
    "category": "misc",
    "description": "Prediction-market odds (Polymarket public CLOB markets)."
  },
  {
    "code": "PORT",
    "name": "Portfolio Analytics",
    "category": "portfolio",
    "description": ""
  },
  {
    "code": "PORT_OPT",
    "name": "Portfolio Optimizer",
    "category": "portfolio",
    "description": "Markowitz min-vol / max-Sharpe / risk-parity / efficient frontier."
  },
  {
    "code": "PORT_WHATIF",
    "name": "Portfolio What-If",
    "category": "portfolio",
    "description": ""
  },
  {
    "code": "PSC",
    "name": "Position Sizing Calculator",
    "category": "portfolio",
    "description": "Risk-based position sizing with R-multiples and Kelly fraction."
  },
  {
    "code": "PVAR",
    "name": "Position-level VaR / MCR",
    "category": "portfolio",
    "description": "Per-symbol marginal contribution to portfolio risk + parametric VaR decomposition."
  },
  {
    "code": "READ",
    "name": "Personalized News (For You)",
    "category": "news",
    "description": ""
  },
  {
    "code": "REBA",
    "name": "Portfolio Rebalancer",
    "category": "portfolio",
    "description": "Compute orders to bring current portfolio to target weights."
  },
  {
    "code": "REGM",
    "name": "Market Regime",
    "category": "macro",
    "description": "Classify regime via trend + vol + drawdown + curve, optionally cluster history."
  },
  {
    "code": "RPAR",
    "name": "Risk Parity (ERC)",
    "category": "portfolio",
    "description": "Compute equal-risk-contribution weights for given universe."
  },
  {
    "code": "RV",
    "name": "Relative Valuation",
    "category": "equity",
    "description": ""
  },
  {
    "code": "SAT",
    "name": "Satellite Imagery",
    "category": "misc",
    "description": "Sentinel-2 true-color PNG + NDVI stats for a bbox + date window."
  },
  {
    "code": "SECF",
    "name": "Security Finder",
    "category": "screen",
    "description": ""
  },
  {
    "code": "SECT",
    "name": "Sector Heatmap",
    "category": "screen",
    "description": "S&P 500 sector ETF day/MTD/QTD/YTD performance heatmap."
  },
  {
    "code": "SOSC",
    "name": "Social Sentiment",
    "category": "news",
    "description": ""
  },
  {
    "code": "SPLC",
    "name": "Supply Chain (approximate)",
    "category": "equity",
    "description": ""
  },
  {
    "code": "SRCH",
    "name": "Bond Screener",
    "category": "screen",
    "description": ""
  },
  {
    "code": "SRSK",
    "name": "Sovereign Risk",
    "category": "bond",
    "description": ""
  },
  {
    "code": "STRS",
    "name": "Portfolio Stress Test",
    "category": "portfolio",
    "description": "Apply historical and custom shock scenarios to portfolio."
  },
  {
    "code": "TAUC",
    "name": "Treasury Auction Calendar",
    "category": "bond",
    "description": "Upcoming + recent Treasury auctions (Bills/Notes/Bonds/TIPS/FRN)."
  },
  {
    "code": "TCA",
    "name": "Trade Cost Analysis",
    "category": "trade",
    "description": "Implementation shortfall, slippage, opportunity cost across fills."
  },
  {
    "code": "TECH",
    "name": "Technical Indicators",
    "category": "chart",
    "description": "30+ technical indicators (RSI/MACD/ATR/Bollinger/Stochastic/ADX/OBV/Ichimoku/...)"
  },
  {
    "code": "TLDR",
    "name": "Daily TL;DR",
    "category": "news",
    "description": "LLM-summarised portfolio + watchlist day in 5 bullets."
  },
  {
    "code": "TLH",
    "name": "Tax-Loss Harvesting",
    "category": "portfolio",
    "description": "Suggest loss lots to sell, estimate tax savings, propose wash-sale-safe swaps."
  },
  {
    "code": "TOP",
    "name": "Top News",
    "category": "news",
    "description": ""
  },
  {
    "code": "TRA",
    "name": "Total Return Analysis",
    "category": "portfolio",
    "description": ""
  },
  {
    "code": "TRAN",
    "name": "Earnings Call Transcripts",
    "category": "news",
    "description": ""
  },
  {
    "code": "TRDH",
    "name": "Trading Hours",
    "category": "macro",
    "description": "Per-exchange trading session status + next open/close (UTC)."
  },
  {
    "code": "TRQA",
    "name": "Transcript Q&A",
    "category": "news",
    "description": "Run a list of questions against an earnings call transcript / audio."
  },
  {
    "code": "TSAR",
    "name": "Transcript Search",
    "category": "news",
    "description": "Search across stored earnings call transcripts (FTS5)."
  },
  {
    "code": "TSOX",
    "name": "Treasury Order Entry",
    "category": "trade",
    "description": ""
  },
  {
    "code": "WACC",
    "name": "Weighted Average Cost of Capital",
    "category": "equity",
    "description": ""
  },
  {
    "code": "WB",
    "name": "World Bonds",
    "category": "bond",
    "description": ""
  },
  {
    "code": "WCRS",
    "name": "World Cross Rates",
    "category": "fx",
    "description": ""
  },
  {
    "code": "WEI",
    "name": "World Equity Indices",
    "category": "screen",
    "description": ""
  },
  {
    "code": "WETR",
    "name": "Weather Trends",
    "category": "commodity",
    "description": ""
  },
  {
    "code": "WHAL",
    "name": "Whale Alerts",
    "category": "misc",
    "description": "Large on-chain transfers + balance moves (Glassnode + Etherscan + Mempool)."
  },
  {
    "code": "WIRP",
    "name": "World Interest Rate Probability",
    "category": "macro",
    "description": ""
  },
  {
    "code": "YAS",
    "name": "Yield & Spread Analytics",
    "category": "bond",
    "description": ""
  }
];
