"""Exchange registry: tickers' exchange suffix conventions.

yfinance / Yahoo append a suffix per non-US exchange (e.g. ``THYAO.IS`` for
Borsa Istanbul). This table lets the SymbolRegistry pick the right suffix
when the user types a bare ticker.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Exchange:
    code: str               # e.g. "BIST"
    name: str               # "Borsa Istanbul"
    country: str            # ISO-3166 alpha-2 (TR, US, GB...)
    currency: str           # default trading currency
    yfinance_suffix: str    # ".IS"  ('' for US)
    timezone: str
    open_local: str         # "09:30"
    close_local: str        # "16:00"


EXCHANGES: dict[str, Exchange] = {
    "NASDAQ": Exchange("NASDAQ", "Nasdaq",                   "US", "USD", "",       "America/New_York",  "09:30", "16:00"),
    "NYSE":   Exchange("NYSE",   "New York Stock Exchange", "US", "USD", "",       "America/New_York",  "09:30", "16:00"),
    "LSE":    Exchange("LSE",    "London Stock Exchange",    "GB", "GBP", ".L",     "Europe/London",     "08:00", "16:30"),
    "PAR":    Exchange("PAR",    "Euronext Paris",           "FR", "EUR", ".PA",    "Europe/Paris",      "09:00", "17:30"),
    "AMS":    Exchange("AMS",    "Euronext Amsterdam",       "NL", "EUR", ".AS",    "Europe/Amsterdam",  "09:00", "17:30"),
    "BRU":    Exchange("BRU",    "Euronext Brussels",        "BE", "EUR", ".BR",    "Europe/Brussels",   "09:00", "17:30"),
    "FWB":    Exchange("FWB",    "Frankfurt (Xetra)",        "DE", "EUR", ".DE",    "Europe/Berlin",     "09:00", "17:30"),
    "SWX":    Exchange("SWX",    "SIX Swiss Exchange",       "CH", "CHF", ".SW",    "Europe/Zurich",     "09:00", "17:30"),
    "BIT":    Exchange("BIT",    "Borsa Italiana",           "IT", "EUR", ".MI",    "Europe/Rome",       "09:00", "17:30"),
    "MAD":    Exchange("MAD",    "Bolsa de Madrid",          "ES", "EUR", ".MC",    "Europe/Madrid",     "09:00", "17:30"),
    "STO":    Exchange("STO",    "Stockholm",                "SE", "SEK", ".ST",    "Europe/Stockholm",  "09:00", "17:30"),
    "OSL":    Exchange("OSL",    "Oslo Bors",                "NO", "NOK", ".OL",    "Europe/Oslo",       "09:00", "16:30"),
    "CPH":    Exchange("CPH",    "Copenhagen",               "DK", "DKK", ".CO",    "Europe/Copenhagen", "09:00", "16:55"),
    "HEL":    Exchange("HEL",    "Helsinki",                 "FI", "EUR", ".HE",    "Europe/Helsinki",   "09:00", "17:25"),
    "ATH":    Exchange("ATH",    "Athens",                   "GR", "EUR", ".AT",    "Europe/Athens",     "10:30", "17:00"),
    "WSE":    Exchange("WSE",    "Warsaw",                   "PL", "PLN", ".WA",    "Europe/Warsaw",     "09:00", "17:00"),
    "PRG":    Exchange("PRG",    "Prague",                   "CZ", "CZK", ".PR",    "Europe/Prague",     "09:00", "16:30"),
    "BIST":   Exchange("BIST",   "Borsa Istanbul",           "TR", "TRY", ".IS",    "Europe/Istanbul",   "10:00", "18:00"),
    "TADAW":  Exchange("TADAW",  "Saudi Tadawul",            "SA", "SAR", ".SR",    "Asia/Riyadh",       "10:00", "15:00"),
    "DFM":    Exchange("DFM",    "Dubai Financial Market",   "AE", "AED", ".DU",    "Asia/Dubai",        "10:00", "15:00"),
    "TASE":   Exchange("TASE",   "Tel Aviv",                 "IL", "ILS", ".TA",    "Asia/Jerusalem",    "09:30", "17:30"),
    "JSE":    Exchange("JSE",    "Johannesburg",             "ZA", "ZAR", ".JO",    "Africa/Johannesburg","09:00","17:00"),
    "EGX":    Exchange("EGX",    "Egyptian Exchange",        "EG", "EGP", ".CA",    "Africa/Cairo",      "10:00", "14:30"),
    "MOEX":   Exchange("MOEX",   "Moscow Exchange",          "RU", "RUB", ".ME",    "Europe/Moscow",     "10:00", "18:45"),
    "TSX":    Exchange("TSX",    "Toronto",                  "CA", "CAD", ".TO",    "America/Toronto",   "09:30", "16:00"),
    "TSXV":   Exchange("TSXV",   "TSX Venture",              "CA", "CAD", ".V",     "America/Toronto",   "09:30", "16:00"),
    "BMV":    Exchange("BMV",    "Mexican Bolsa",            "MX", "MXN", ".MX",    "America/Mexico_City","08:30","15:00"),
    "B3":     Exchange("B3",     "Brasil Bolsa",             "BR", "BRL", ".SA",    "America/Sao_Paulo", "10:00", "17:55"),
    "BCBA":   Exchange("BCBA",   "Buenos Aires",             "AR", "ARS", ".BA",    "America/Argentina/Buenos_Aires", "11:00","17:00"),
    "BCS":    Exchange("BCS",    "Santiago",                 "CL", "CLP", ".SN",    "America/Santiago",  "09:30", "16:00"),
    "BVL":    Exchange("BVL",    "Lima",                     "PE", "PEN", ".LM",    "America/Lima",      "09:00", "16:00"),
    "BVC":    Exchange("BVC",    "Colombia",                 "CO", "COP", ".CL",    "America/Bogota",    "09:00", "16:00"),
    "TYO":    Exchange("TYO",    "Tokyo",                    "JP", "JPY", ".T",     "Asia/Tokyo",        "09:00", "15:00"),
    "OSE":    Exchange("OSE",    "Osaka Exchange",           "JP", "JPY", ".OS",    "Asia/Tokyo",        "09:00", "15:00"),
    "HKEX":   Exchange("HKEX",   "Hong Kong",                "HK", "HKD", ".HK",    "Asia/Hong_Kong",    "09:30", "16:00"),
    "SSE":    Exchange("SSE",    "Shanghai",                 "CN", "CNY", ".SS",    "Asia/Shanghai",     "09:30", "15:00"),
    "SZSE":   Exchange("SZSE",   "Shenzhen",                 "CN", "CNY", ".SZ",    "Asia/Shanghai",     "09:30", "15:00"),
    "TWSE":   Exchange("TWSE",   "Taiwan",                   "TW", "TWD", ".TW",    "Asia/Taipei",       "09:00", "13:30"),
    "KRX":    Exchange("KRX",    "Korea Exchange",           "KR", "KRW", ".KS",    "Asia/Seoul",        "09:00", "15:30"),
    "KQ":     Exchange("KQ",     "KOSDAQ",                   "KR", "KRW", ".KQ",    "Asia/Seoul",        "09:00", "15:30"),
    "BSE":    Exchange("BSE",    "Bombay Stock Exchange",    "IN", "INR", ".BO",    "Asia/Kolkata",      "09:15", "15:30"),
    "NSE_IN": Exchange("NSE_IN", "National Stock Exchange",  "IN", "INR", ".NS",    "Asia/Kolkata",      "09:15", "15:30"),
    "ASX":    Exchange("ASX",    "Australia",                "AU", "AUD", ".AX",    "Australia/Sydney",  "10:00", "16:00"),
    "NZX":    Exchange("NZX",    "New Zealand",              "NZ", "NZD", ".NZ",    "Pacific/Auckland",  "10:00", "16:45"),
    "SGX":    Exchange("SGX",    "Singapore",                "SG", "SGD", ".SI",    "Asia/Singapore",    "09:00", "17:00"),
    "BMK":    Exchange("BMK",    "Bursa Malaysia",           "MY", "MYR", ".KL",    "Asia/Kuala_Lumpur", "09:00", "17:00"),
    "IDX":    Exchange("IDX",    "Indonesia",                "ID", "IDR", ".JK",    "Asia/Jakarta",      "09:00", "16:30"),
    "PSX":    Exchange("PSX",    "Karachi",                  "PK", "PKR", ".KA",    "Asia/Karachi",      "09:30", "15:30"),
    "BVB":    Exchange("BVB",    "Bucharest",                "RO", "RON", ".RO",    "Europe/Bucharest",  "10:00", "17:30"),
    # Crypto
    "BINANCE":  Exchange("BINANCE",  "Binance",                "GLOBAL","USDT","",   "UTC","00:00","23:59"),
    "BYBIT":    Exchange("BYBIT",    "Bybit",                  "GLOBAL","USDT","",   "UTC","00:00","23:59"),
    "OKX":      Exchange("OKX",      "OKX",                    "GLOBAL","USDT","",   "UTC","00:00","23:59"),
    "COINBASE": Exchange("COINBASE", "Coinbase",               "US",    "USD","",    "UTC","00:00","23:59"),
    "DERIBIT":  Exchange("DERIBIT",  "Deribit",                "GLOBAL","USD","",    "UTC","00:00","23:59"),
}


class ExchangeRegistry:
    """Look up exchanges by code, country, currency, or yfinance suffix."""

    def get(self, code: str) -> Exchange | None:
        return EXCHANGES.get(code.upper())

    def by_country(self, country: str) -> list[Exchange]:
        return [e for e in EXCHANGES.values() if e.country == country.upper()]

    def by_currency(self, currency: str) -> list[Exchange]:
        return [e for e in EXCHANGES.values() if e.currency == currency.upper()]

    def by_suffix(self, suffix: str) -> Exchange | None:
        for e in EXCHANGES.values():
            if e.yfinance_suffix == suffix:
                return e
        return None

    def all(self) -> list[Exchange]:
        return list(EXCHANGES.values())
