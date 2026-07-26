import js from "@eslint/js";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";

export default [
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "*.tsbuildinfo",
      "vite.config.d.ts",
      "vite.config.js",
      ".eslintrc.cjs",
      "src/design-export/**",
    ],
  },
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parser: tsParser,
      globals: {
        ...globals.browser,
        ...globals.es2022,
        // Ambient TypeScript types. `no-undef` resolves identifiers
        // lexically and cannot see the type namespace, so without these it
        // reports every `RequestInit` / `JSX.Element` annotation as an
        // undefined reference. Declaring them keeps the rule meaningful
        // instead of drowning real findings in false positives.
        React: "readonly",
        JSX: "readonly",
        RequestInit: "readonly",
        RequestInfo: "readonly",
      },
    },
    linterOptions: {
      reportUnusedDisableDirectives: "off",
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // These two catch real bugs, not style: `no-undef` catches references
      // to identifiers that do not exist, and `exhaustive-deps` catches stale
      // closures in hooks (an effect capturing a value it never refreshes).
      // Both were "off"; they are warnings rather than errors only so the
      // existing backlog does not block the build. Do not switch them back
      // off — fix the call site or add a scoped eslint-disable with a reason.
      "no-undef": "warn",
      "react-hooks/exhaustive-deps": "warn",
      // Style/HMR-ergonomics rules, left off deliberately.
      "react-refresh/only-export-components": "off",
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    // Build config and test files run under Node, not the browser: they use
    // __dirname, process and global legitimately.
    files: [
      "*.config.ts",
      "*.config.js",
      "**/*.test.ts",
      "**/*.test.tsx",
      "**/__tests__/**/*.{ts,tsx}",
      "**/test-utils/**/*.{ts,tsx}",
    ],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },
];
