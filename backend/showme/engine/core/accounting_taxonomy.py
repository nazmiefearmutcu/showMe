"""US-GAAP ↔ IFRS field mapping (basit, genişletilebilir).

Plan §7.2 (FA fonksiyonu) US-GAAP/IFRS uyumlama modülünü Coder'dan istiyor.
İlk pas: en sık 30+ alan için mapping. Daha derin denkleştirme için ileride
``functions/equity/fa.py`` içerisinde adapter genişletilir.
"""

from __future__ import annotations


# US-GAAP XBRL tag → IFRS tag mapping (en sık karşılaşılan kalemler).
# Kaynaklar: SEC EDGAR taxonomy, IFRS Foundation taxonomy 2024,
# Damodaran Financial Statement Cleanup notları.
GAAP_TO_IFRS: dict[str, str] = {
    # Income statement
    "Revenues": "Revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "Revenue",
    "CostOfRevenue": "CostOfSales",
    "GrossProfit": "GrossProfit",
    "OperatingIncomeLoss": "ProfitLossFromOperatingActivities",
    "NetIncomeLoss": "ProfitLoss",
    "EarningsPerShareBasic": "BasicEarningsLossPerShare",
    "EarningsPerShareDiluted": "DilutedEarningsLossPerShare",
    "ResearchAndDevelopmentExpense": "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense": "SellingGeneralAdministrativeExpense",
    "InterestExpense": "FinanceCosts",
    "IncomeTaxExpenseBenefit": "IncomeTaxExpenseContinuingOperations",
    # Balance sheet
    "Assets": "Assets",
    "AssetsCurrent": "CurrentAssets",
    "AssetsNoncurrent": "NoncurrentAssets",
    "Liabilities": "Liabilities",
    "LiabilitiesCurrent": "CurrentLiabilities",
    "LiabilitiesNoncurrent": "NoncurrentLiabilities",
    "StockholdersEquity": "Equity",
    "RetainedEarningsAccumulatedDeficit": "RetainedEarnings",
    "CashAndCashEquivalentsAtCarryingValue": "CashAndCashEquivalents",
    "AccountsReceivableNetCurrent": "TradeAndOtherCurrentReceivables",
    "InventoryNet": "Inventories",
    "PropertyPlantAndEquipmentNet": "PropertyPlantAndEquipment",
    "Goodwill": "Goodwill",
    "IntangibleAssetsNetExcludingGoodwill": "IntangibleAssetsOtherThanGoodwill",
    "LongTermDebt": "NoncurrentBorrowings",
    "AccountsPayableCurrent": "TradeAndOtherCurrentPayables",
    # Cash flow
    "NetCashProvidedByUsedInOperatingActivities": "CashFlowsFromUsedInOperatingActivities",
    "NetCashProvidedByUsedInInvestingActivities": "CashFlowsFromUsedInInvestingActivities",
    "NetCashProvidedByUsedInFinancingActivities": "CashFlowsFromUsedInFinancingActivities",
    "DepreciationAndAmortization": "DepreciationAmortisationAndImpairmentLoss",
    "PaymentsToAcquirePropertyPlantAndEquipment": "PurchaseOfPropertyPlantAndEquipment",
    "PaymentsForRepurchaseOfCommonStock": "PaymentsToAcquireOrRedeemEntitysShares",
}

IFRS_TO_GAAP: dict[str, str] = {v: k for k, v in GAAP_TO_IFRS.items()}


# Canonical "ShowMe standard" field names — used inside FA function output so
# UI code does not care about XBRL taxonomy. Maps from the multitude of
# upstream tag names down to one clean key.
CANONICAL_FIELD: dict[str, str] = {
    # → revenue
    "Revenues": "revenue",
    "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "Revenue": "revenue",
    "SalesRevenueNet": "revenue",
    # → net_income
    "NetIncomeLoss": "net_income",
    "ProfitLoss": "net_income",
    "ProfitLossAttributableToOwnersOfParent": "net_income",
    # → operating_income
    "OperatingIncomeLoss": "operating_income",
    "ProfitLossFromOperatingActivities": "operating_income",
    # → total_assets
    "Assets": "total_assets",
    # → total_liabilities
    "Liabilities": "total_liabilities",
    # → total_equity
    "StockholdersEquity": "total_equity",
    "Equity": "total_equity",
    # → cash
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "CashAndCashEquivalents": "cash",
    # → cfo / cfi / cff
    "NetCashProvidedByUsedInOperatingActivities": "cfo",
    "CashFlowsFromUsedInOperatingActivities": "cfo",
    "NetCashProvidedByUsedInInvestingActivities": "cfi",
    "CashFlowsFromUsedInInvestingActivities": "cfi",
    "NetCashProvidedByUsedInFinancingActivities": "cff",
    "CashFlowsFromUsedInFinancingActivities": "cff",
    # → capex
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "PurchaseOfPropertyPlantAndEquipment": "capex",
    # → debt
    "LongTermDebt": "long_term_debt",
    "NoncurrentBorrowings": "long_term_debt",
}


def to_canonical(field: str) -> str:
    """Return the ShowMe-canonical field name; defaults to lowercase input."""
    return CANONICAL_FIELD.get(field, field[0].lower() + field[1:])


# gaap_to_ifrs / ifrs_to_gaap helpers were removed as dead code (PY-LINT-02);
# every consumer goes through ``to_canonical`` which is the canonical entry point.
