/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          base: "var(--bg-base)",
          panel: "var(--bg-elev-1)",
          card: "var(--bg-elev-2)",
        },
        accent: "var(--accent)",
        positive: "var(--positive)",
        negative: "var(--negative)",
        neutral: "var(--neutral)",
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        subtle: "var(--border-subtle)",
      },
      fontFamily: {
        sans: ["SF Pro Text", "SF Pro Display", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "ui-monospace", "monospace"],
      },
      fontSize: {
        "10": ["10px", "14px"],
        "11": ["11px", "16px"],
        "13": ["13px", "18px"],
        "15": ["15px", "22px"],
        "17": ["17px", "24px"],
        "22": ["22px", "30px"],
        "28": ["28px", "36px"],
      },
      transitionTimingFunction: {
        "swift": "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
    },
  },
  plugins: [],
};
