export type Theme = "light" | "dark";

export const THEME_KEY = "jarvis-theme-v1";

export function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = localStorage.getItem(THEME_KEY) as Theme | null;
  if (saved === "light" || saved === "dark") return saved;
  return "dark"; // default to dark
}

export function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  // Keep the .dark class in sync for any selectors that still use it
  if (theme === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
}

export function persistTheme(theme: Theme): void {
  localStorage.setItem(THEME_KEY, theme);
}
