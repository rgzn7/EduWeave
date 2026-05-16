import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#132022",
        paper: "#f7f5ef",
        line: "#d8d6cf",
        accent: "#0f8b8d",
        coral: "#d96846",
        leaf: "#3f7d58",
        gold: "#c79b33",
      },
      boxShadow: {
        panel: "0 18px 50px rgba(19, 32, 34, 0.08)",
      },
    },
  },
  plugins: [],
} satisfies Config;
