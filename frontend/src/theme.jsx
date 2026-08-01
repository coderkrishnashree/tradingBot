import { createContext, useContext, useEffect, useState } from "react";

// Global UI theme: "universe" (dark galaxy, animated) | "table" (clean, flat).
// Persisted in localStorage; applied as data-theme on <html> so every CSS
// token flips at once. Components read useTheme() to swap layouts.
const ThemeCtx = createContext({ theme: "universe", setTheme: () => {}, isUniverse: true });

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    const t = localStorage.getItem("uiTheme");
    return t === "table" ? "table" : "universe";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
  const setTheme = (t) => { localStorage.setItem("uiTheme", t); setThemeState(t); };
  return (
    <ThemeCtx.Provider value={{ theme, setTheme, isUniverse: theme === "universe" }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export const useTheme = () => useContext(ThemeCtx);

// The header switch. Text + glyph on both options (never color-alone).
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const opt = (key, glyph, label) => (
    <button
      key={key}
      onClick={() => setTheme(key)}
      aria-pressed={theme === key}
      title={`Switch to ${label} theme`}
      className={`btn text-xs py-1.5 px-2.5 ${
        theme === key
          ? "bg-accent/20 text-accent ring-1 ring-accent/50"
          : "text-slate-400 hover:text-slate-100 hover:bg-white/[0.06]"
      }`}
    >
      {glyph} {label}
    </button>
  );
  return (
    <div className="flex items-center gap-1" role="group" aria-label="UI theme">
      {opt("universe", "✦", "Universe")}
      {opt("table", "▦", "Table")}
    </div>
  );
}

// Read a theme token for canvas/SVG code that needs concrete color strings.
// Tokens are stored as "R G B" triplets on :root.
export function tokenRGB(name, alpha = 1) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (v) return `rgba(${v.split(/\s+/).join(",")},${alpha})`;
  } catch { /* SSR/test */ }
  return `rgba(167,139,250,${alpha})`;
}
