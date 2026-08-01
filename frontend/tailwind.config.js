/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // J.A.R.V.I.S holo-HUD palette: deep blue-black surfaces + arc-reactor cyan.
        ink: {
          950: "#020608", // page background (deepest)
          900: "#04101a", // card background
          850: "#071a29", // raised inner surfaces
          800: "#0a2436", // hover / inputs
          700: "#0f3549", // borders / chips
          600: "#166080",
        },
        accent: "#00e5ff",   // arc-reactor cyan
        accent2: "#7df9ff",
        up: "#00ffa3",       // profit / long (neon green)
        down: "#ff3b5c",     // loss / short (alert red)
      },
      fontFamily: {
        sans: ["Rajdhani", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Orbitron", "Rajdhani", "sans-serif"],
        mono: ["Share Tech Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 0 0 1px rgba(0,229,255,0.06) inset, 0 0 28px -10px rgba(0,229,255,0.18), 0 10px 30px -14px rgba(0,0,0,0.85)",
        glow: "0 0 12px rgba(0,229,255,0.45)",
      },
    },
  },
  plugins: [],
};
