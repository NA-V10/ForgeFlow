import type { Config } from "tailwindcss";

const color = (name: string) => `hsl(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: color("border"),
        input: color("input"),
        ring: color("ring"),
        background: color("background"),
        foreground: color("foreground"),
        panel: color("panel"),
        elevated: color("elevated"),
        agent: color("agent"),
        muted: { DEFAULT: color("muted"), foreground: color("muted-foreground") },
        accent: { DEFAULT: color("accent"), foreground: color("accent-foreground") },
        primary: { DEFAULT: color("primary"), foreground: color("primary-foreground") },
        destructive: { DEFAULT: color("destructive"), foreground: color("destructive-foreground") },
        success: color("success"),
        warning: color("warning"),
        info: color("info"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: { lg: "10px", md: "7px", sm: "5px" },
      fontSize: { "2xs": ["10.5px", "14px"] },
    },
  },
  plugins: [],
} satisfies Config;
