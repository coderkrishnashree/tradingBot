/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Dark "trading terminal" palette.
        ink: {
          900: "#0a0e17", // page background
          800: "#0f1622", // card background
          700: "#161f2e", // raised / header
          600: "#1f2a3c", // borders
        },
        accent: "#3b82f6",
        up: "#22c55e",   // green / profit / paper
        down: "#ef4444", // red / loss / live
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
