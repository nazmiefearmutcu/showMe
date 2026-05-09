"""Currency registry: ISO 4217 metadata + cross-rate cache."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Currency:
    code: str            # ISO 4217 (USD, EUR, TRY)
    name: str
    minor_units: int     # decimal places (USD=2, JPY=0, KWD=3)
    symbol: str          # "$", "€", "₺", ...


CURRENCIES: dict[str, Currency] = {
    "USD": Currency("USD", "US Dollar",        2, "$"),
    "EUR": Currency("EUR", "Euro",             2, "€"),
    "GBP": Currency("GBP", "Pound Sterling",   2, "£"),
    "JPY": Currency("JPY", "Japanese Yen",     0, "¥"),
    "CHF": Currency("CHF", "Swiss Franc",      2, "Fr"),
    "AUD": Currency("AUD", "Australian Dollar",2, "A$"),
    "CAD": Currency("CAD", "Canadian Dollar",  2, "C$"),
    "NZD": Currency("NZD", "NZ Dollar",        2, "NZ$"),
    "TRY": Currency("TRY", "Turkish Lira",     2, "₺"),
    "RUB": Currency("RUB", "Russian Ruble",    2, "₽"),
    "CNY": Currency("CNY", "Chinese Yuan",     2, "¥"),
    "HKD": Currency("HKD", "HK Dollar",        2, "HK$"),
    "SGD": Currency("SGD", "SG Dollar",        2, "S$"),
    "INR": Currency("INR", "Indian Rupee",     2, "₹"),
    "KRW": Currency("KRW", "Korean Won",       0, "₩"),
    "BRL": Currency("BRL", "Brazilian Real",   2, "R$"),
    "MXN": Currency("MXN", "Mexican Peso",     2, "$"),
    "ZAR": Currency("ZAR", "South African Rand",2,"R"),
    "SEK": Currency("SEK", "Swedish Krona",    2, "kr"),
    "NOK": Currency("NOK", "Norwegian Krone",  2, "kr"),
    "DKK": Currency("DKK", "Danish Krone",     2, "kr"),
    "PLN": Currency("PLN", "Polish Zloty",     2, "zł"),
    "AED": Currency("AED", "UAE Dirham",       2, "د.إ"),
    "SAR": Currency("SAR", "Saudi Riyal",      2, "ر.س"),
    "ILS": Currency("ILS", "Israeli Shekel",   2, "₪"),
    "USDT":Currency("USDT","Tether USD",       6, "₮"),
    "USDC":Currency("USDC","USD Coin",         6, "$"),
}


class CurrencyRegistry:
    def get(self, code: str) -> Currency | None:
        return CURRENCIES.get(code.upper())

    def all(self) -> list[Currency]:
        return list(CURRENCIES.values())

    def format(self, amount: float, code: str) -> str:
        c = self.get(code) or CURRENCIES["USD"]
        return f"{c.symbol}{amount:,.{c.minor_units}f}"
