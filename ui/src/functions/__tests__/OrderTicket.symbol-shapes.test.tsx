/**
 * Bug #10c — OrderTicket symbol regex rejected 60+ exchanges.
 *
 * The previous regex `^[A-Z0-9]+/[A-Z0-9]+$` only matched spot pairs.
 * `isValidSymbolForExchange()` now picks the rule from the exchange id
 * so ccxt-swap (`BTC/USDT:USDT`), Deribit/dYdX perp (`BTC-PERP`), and
 * Alpaca equity (`AAPL`, `BRK.B`) all validate.
 */
import { describe, expect, it } from "vitest";
import { isValidSymbolForExchange } from "../OrderTicket";

describe("isValidSymbolForExchange — Bug #10c", () => {
  describe("spot/swap exchanges (default)", () => {
    it("accepts spot pairs", () => {
      expect(isValidSymbolForExchange("BTC/USDT", "binance")).toBe(true);
      expect(isValidSymbolForExchange("ETH/USDT", "kraken")).toBe(true);
      expect(isValidSymbolForExchange("SOL/USDC", "okx")).toBe(true);
    });

    it("accepts ccxt swap notation", () => {
      expect(isValidSymbolForExchange("BTC/USDT:USDT", "binance")).toBe(true);
      expect(isValidSymbolForExchange("ETH/USD:USD", "kraken")).toBe(true);
      expect(isValidSymbolForExchange("SOL/USDC:USDC", "okx")).toBe(true);
    });

    it("rejects garbage", () => {
      expect(isValidSymbolForExchange("BTCUSDT", "binance")).toBe(false);
      expect(isValidSymbolForExchange("btc/usdt", "binance")).toBe(false);
      expect(isValidSymbolForExchange("", "binance")).toBe(false);
      expect(isValidSymbolForExchange("BTC/", "binance")).toBe(false);
      expect(isValidSymbolForExchange("/USDT", "binance")).toBe(false);
    });
  });

  describe("Alpaca equity", () => {
    it("accepts plain tickers", () => {
      expect(isValidSymbolForExchange("AAPL", "alpaca")).toBe(true);
      expect(isValidSymbolForExchange("MSFT", "alpaca")).toBe(true);
      expect(isValidSymbolForExchange("V", "alpaca")).toBe(true);
    });

    it("accepts tickers with dots (BRK.B-style classes)", () => {
      expect(isValidSymbolForExchange("BRK.B", "alpaca")).toBe(true);
      expect(isValidSymbolForExchange("BF.B", "alpaca")).toBe(true);
    });

    it("rejects spot/swap shapes on equity exchanges", () => {
      expect(isValidSymbolForExchange("BTC/USDT", "alpaca")).toBe(false);
      expect(isValidSymbolForExchange("BTC/USDT:USDT", "alpaca")).toBe(false);
      expect(isValidSymbolForExchange("BTC-PERP", "alpaca")).toBe(false);
    });

    it("rejects lowercase tickers", () => {
      expect(isValidSymbolForExchange("aapl", "alpaca")).toBe(false);
    });
  });

  describe("Deribit / dYdX perps", () => {
    it("accepts the BASE-PERP shape", () => {
      expect(isValidSymbolForExchange("BTC-PERP", "deribit")).toBe(true);
      expect(isValidSymbolForExchange("ETH-PERP", "dydx")).toBe(true);
    });

    it("accepts ccxt swap form too (Deribit ships both)", () => {
      expect(isValidSymbolForExchange("BTC/USDT:USDT", "deribit")).toBe(true);
    });

    it("rejects plain spot on perp adapters", () => {
      expect(isValidSymbolForExchange("BTC/USDT", "deribit")).toBe(false);
    });
  });

  describe("case-insensitive exchange id", () => {
    it("ALPACA in uppercase still routes to equity rule", () => {
      expect(isValidSymbolForExchange("AAPL", "ALPACA")).toBe(true);
      expect(isValidSymbolForExchange("BTC/USDT", "ALPACA")).toBe(false);
    });
  });
});
