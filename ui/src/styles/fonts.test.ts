/**
 * Font bundling regression tests — L1 terminal-grade campaign (2026-09-11).
 *
 * The type system used to be declared-but-never-loaded (survey-2 C1):
 * tokens.css named JetBrains Mono / Inter Tight / VT323 / Share Tech Mono
 * while the repo shipped zero font bytes, so Windows fell back to
 * Courier New / Segoe UI. These tests pin the fix structurally:
 *
 *   1. every @font-face in fonts.css resolves to a real file in
 *      ui/public/fonts/ (the dir Vite copies verbatim to the site root);
 *   2. the declared family/weight matrix matches what we vendored;
 *   3. faces use font-display: swap + normal style;
 *   4. tokens.css stacks still name the bundled families;
 *   5. fonts.css is imported before tokens.css (registration order);
 *   6. index.html preloads the two primary faces.
 */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "fonts.css"), "utf8");
const tokensCss = readFileSync(resolve(__dirname, "tokens.css"), "utf8");
const indexCss = readFileSync(resolve(__dirname, "index.css"), "utf8");
const indexHtml = readFileSync(resolve(__dirname, "../../index.html"), "utf8");
const fontsDir = resolve(__dirname, "../../public/fonts");

interface Face {
  family: string;
  weight: string;
  style: string;
  display: string;
  file: string;
}

const faces: Face[] = [];
const blockRe = /@font-face\s*\{([\s\S]*?)\}/g;
let m: RegExpExecArray | null;
while ((m = blockRe.exec(css)) !== null) {
  const body = m[1] ?? "";
  const family = /font-family:\s*"([^"]+)"/.exec(body)?.[1] ?? "";
  const weight = /font-weight:\s*(\d+)/.exec(body)?.[1] ?? "";
  const style = /font-style:\s*([a-z]+)/.exec(body)?.[1] ?? "";
  const display = /font-display:\s*([a-z]+)/.exec(body)?.[1] ?? "";
  const file = /url\("\/fonts\/([^"]+)"\)/.exec(body)?.[1] ?? "";
  faces.push({ family, weight, style, display, file });
}

/** Family / weight / file matrix this lane vendored from fontsource. */
const EXPECTED: Array<[string, string, string]> = [
  ["JetBrains Mono", "400", "jetbrains-mono-latin-400-normal.woff2"],
  ["JetBrains Mono", "500", "jetbrains-mono-latin-500-normal.woff2"],
  ["JetBrains Mono", "600", "jetbrains-mono-latin-600-normal.woff2"],
  ["JetBrains Mono", "700", "jetbrains-mono-latin-700-normal.woff2"],
  ["Inter Tight", "400", "inter-tight-latin-400-normal.woff2"],
  ["Inter Tight", "500", "inter-tight-latin-500-normal.woff2"],
  ["Inter Tight", "600", "inter-tight-latin-600-normal.woff2"],
  ["Inter Tight", "700", "inter-tight-latin-700-normal.woff2"],
  ["Share Tech Mono", "400", "share-tech-mono-latin-400-normal.woff2"],
  ["VT323", "400", "vt323-latin-400-normal.woff2"],
];

describe("bundled typography", () => {
  it("declares exactly the vendored family/weight matrix", () => {
    expect(faces).toHaveLength(EXPECTED.length);
    for (const [family, weight, file] of EXPECTED) {
      const found = faces.find((f) => f.family === family && f.weight === weight);
      expect(found, `missing @font-face ${family} ${weight}`).toBeTruthy();
      expect(found?.file).toBe(file);
    }
  });

  it("points every @font-face at a real woff2 file in public/fonts", () => {
    expect(faces.length).toBeGreaterThan(0);
    for (const face of faces) {
      const filePath = resolve(fontsDir, face.file);
      expect(existsSync(filePath), `missing font file ${face.file}`).toBe(true);
      const size = statSync(filePath).size;
      // Latin-subset woff2 faces are 13-23KB; a tiny file means a bad fetch.
      expect(size, `${face.file} too small`).toBeGreaterThan(4096);
      const magic = readFileSync(filePath).subarray(0, 4).toString("ascii");
      expect(magic, `${face.file} is not woff2`).toBe("wOF2");
    }
  });

  it("loads every face with font-display: swap and normal style", () => {
    for (const face of faces) {
      expect(face.display, `${face.family} ${face.weight}`).toBe("swap");
      expect(face.style, `${face.family} ${face.weight}`).toBe("normal");
    }
  });

  it("ships the tabular-numerals utility", () => {
    expect(css).toMatch(/\.u-tabular\s*\{[^}]*font-variant-numeric:\s*tabular-nums/);
  });

  it("tokens.css stacks name the bundled families", () => {
    // Default (root/midnight) stacks.
    expect(tokensCss).toMatch(/--font-mono:\s*"JetBrains Mono"/);
    expect(tokensCss).toMatch(/--font-display:\s*"Inter Tight"/);
    // Matrix preset swaps to the bundled terminal faces (slot block).
    const matrixSlot = tokensCss.split('[data-preset="matrix"]')[1] ?? "";
    expect(matrixSlot).toMatch(/--font-display:\s*"VT323", "Share Tech Mono"/);
    expect(matrixSlot).toMatch(/--font-text:\s*"Share Tech Mono"/);
    expect(matrixSlot).toMatch(/--font-mono:\s*"Share Tech Mono"/);
  });

  it("imports fonts.css before tokens.css in index.css", () => {
    const fontsImport = indexCss.indexOf('@import "./fonts.css"');
    const tokensImport = indexCss.indexOf('@import "./tokens.css"');
    expect(fontsImport).toBeGreaterThanOrEqual(0);
    expect(tokensImport).toBeGreaterThan(fontsImport);
  });

  it("index.html preloads the two primary faces", () => {
    expect(indexHtml).toMatch(
      /<link rel="preload" as="font" type="font\/woff2" crossorigin href="\/fonts\/jetbrains-mono-latin-400-normal\.woff2"/,
    );
    expect(indexHtml).toMatch(
      /<link rel="preload" as="font" type="font\/woff2" crossorigin href="\/fonts\/inter-tight-latin-400-normal\.woff2"/,
    );
  });
});
