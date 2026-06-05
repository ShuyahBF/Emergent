/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // SAWALI brand
        // Iter40-ui-flags — Brand colors are resolved via CSS variables so
        // changing public_brand_color in Admin Settings retints every
        // `bg-sawali-blue`, `text-sawali-blue`, `border-sawali-blue`,
        // `ring-sawali-blue`, etc. instantly across the app.
        // Defaults (when var unset) are the historical SAWALI hex codes.
        sawali: {
          navy: "#0E1F3D",
          "navy-dark": "#081226",
          blue: "var(--brand-primary, #1E90FF)",
          "blue-light": "var(--brand-primary-light, #2BA4FF)",
          cyan: "#00E5FF",
        },
        // Iter40-ui-flags — Semantic aliases for new components. Prefer these.
        brand: {
          DEFAULT: "var(--brand-primary, #1E90FF)",
          light: "var(--brand-primary-light, #2BA4FF)",
          dark: "var(--brand-primary-dark, #1873CC)",
          text: "var(--brand-text, #FFFFFF)",
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', "sans-serif"],
        body: ['"Geist"', "Inter", "sans-serif"],
        mono: ['"Geist Mono"', "ui-monospace", "monospace"],
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "fade-up": { "0%": { opacity: "0", transform: "translateY(16px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        "pulse-glow": { "0%,100%": { boxShadow: "0 0 0 0 rgba(30,144,255,0.4)" }, "50%": { boxShadow: "0 0 0 12px rgba(30,144,255,0)" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-up": "fade-up 0.6s ease-out forwards",
        "pulse-glow": "pulse-glow 2.4s ease-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
