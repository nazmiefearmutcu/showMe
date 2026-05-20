/**
 * Template registry — flat map of fn-code → templated marker. Generated
 * from mock-data.ts. Consumed by scripts/verify_template_integration.mjs
 * to assert every design-templated code has a Basic renderer.
 */
import { listMockCodes } from "./mock-data";

export const TEMPLATE_BACKED_CODES: Record<string, true> = Object.fromEntries(
  listMockCodes().map((code) => [code, true as const]),
);

export function isTemplateBacked(code: string): boolean {
  return !!TEMPLATE_BACKED_CODES[code.toUpperCase()];
}

export function templateBackedList(): string[] {
  return Object.keys(TEMPLATE_BACKED_CODES).sort();
}
