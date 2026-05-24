import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111111",
        paper: "#ffffff",
        line: "#e6e6e6",
        accent: "#111111",
        coral: "#b54708",
        leaf: "#111111",
        gold: "#a16207",
      },
      boxShadow: {
        panel: "0 18px 48px rgba(17, 17, 17, 0.055)",
      },
    },
  },
  plugins: [],
} satisfies Config;
