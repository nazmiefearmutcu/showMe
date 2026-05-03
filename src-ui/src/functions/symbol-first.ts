const SYMBOL_FIRST_CODES = new Set([
  "ANR",
  "BETA",
  "CACT",
  "CN",
  "DARK",
  "DCF",
  "DCFS",
  "DDM",
  "DES",
  "DPF",
  "DVD",
  "EE",
  "ESG",
  "FA",
  "FORM4",
  "FTS",
  "GEX",
  "GP",
  "HDS",
  "HFS",
  "HP",
  "HVT",
  "IVOL",
  "LITM",
  "NALRT",
  "NI",
  "OMON",
  "PIB",
  "RV",
  "SPLC",
  "TECH",
  "WACC",
]);

const SYMBOL_FIRST_CATEGORIES = new Set(["chart", "equity"]);

export function isSymbolFirstFunction(code: string, category?: string): boolean {
  if (SYMBOL_FIRST_CODES.has(code.toUpperCase())) return true;
  if (!category) return false;
  return SYMBOL_FIRST_CATEGORIES.has(category.toLowerCase());
}
