/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Modern dark "trading terminal" palette.
        ink: {
          950: "#07080c", // page background (deepest)
          900: "#0c0e14", // card background
          850: "#11141c", // raised inner surfaces
          800: "#161a24", // hover / inputs
          700: "#212636", // borders / chips
          600: "#2c3348",
        },
        accent: "#6366f1",   // indigo
        accent2: "#818cf8",
        up: "#22c55e",       // profit / long
        down: "#ef4444",     // loss / short
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};
