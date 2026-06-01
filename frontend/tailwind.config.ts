import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#6C5CE7", dark: "#4834d4", accent: "#00CEC9" },
        ink: "#1e2235",
      },
    },
  },
  plugins: [],
};

export default config;
