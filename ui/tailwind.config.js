/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surface ladder (3 tiers)
        bg: "var(--bg)",
        surface: {
          DEFAULT: "var(--surface)",
          1: "var(--surface-1)",
          2: "var(--surface-2)",
          3: "var(--surface-3)",
          glass: "var(--surface-glass)",
        },
        // Legacy aliases (do not break existing className refs)
        ink: {
          base: "var(--bg)",
          panel: "var(--surface-1)",
          card: "var(--surface-2)",
        },
        // Accent family
        accent: {
          DEFAULT: "var(--accent)",
          soft: "var(--accent-soft)",
          strong: "var(--accent-strong)",
          on: "var(--accent-on)",
        },
        // Semantic
        positive: {
          DEFAULT: "var(--positive)",
          soft: "var(--positive-soft)",
        },
        negative: {
          DEFAULT: "var(--negative)",
          soft: "var(--negative-soft)",
        },
        warn: {
          DEFAULT: "var(--warn)",
          soft: "var(--warn-soft)",
        },
        neutral: "var(--neutral)",
        // Text
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        mute: "var(--text-mute)",
        display: "var(--text-display)",
        // Borders
        subtle: "var(--border-subtle)",
        strong: "var(--border-strong)",
        row: "var(--border-row)",
        card: "var(--border-card)",
      },
      fontFamily: {
        sans: ["SF Pro Text", "SF Pro Display", "system-ui", "sans-serif"],
        display: ["Inter Tight", "SF Pro Display", "system-ui", "sans-serif"],
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
        "32": ["32px", "40px"],
        "36": ["36px", "44px"],
        "40": ["40px", "48px"],
      },
      letterSpacing: {
        caps: "0.06em",
      },
      borderRadius: {
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        pill: "var(--radius-pill)",
      },
      spacing: {
        // Tokens — ladder mirrored from tokens.css --space-*.
        s1: "var(--space-1)",
        s2: "var(--space-2)",
        s3: "var(--space-3)",
        s4: "var(--space-4)",
        s5: "var(--space-5)",
        s6: "var(--space-6)",
        s7: "var(--space-7)",
        s8: "var(--space-8)",
      },
      zIndex: {
        sticky: "var(--z-sticky)",
        dropdown: "var(--z-dropdown)",
        popover: "var(--z-popover)",
        toast: "var(--z-toast)",
        modal: "var(--z-modal)",
        confirm: "var(--z-confirm)",
        splash: "var(--z-splash)",
      },
      transitionTimingFunction: {
        swift: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      },
      boxShadow: {
        elev: "var(--shadow-elev)",
        "elev-1": "var(--shadow-elev-1)",
        "elev-2": "var(--shadow-elev-2)",
        "elev-3": "var(--shadow-elev-3)",
      },
    },
  },
  plugins: [],
};
