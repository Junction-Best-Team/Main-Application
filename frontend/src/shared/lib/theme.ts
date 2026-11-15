// Light/dark theme on <html data-theme>. A saved choice wins; otherwise the OS preference.
export type Theme = "light" | "dark";

const STORAGE_KEY = "aimo-theme";

function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#0b1418" : "#003d59");
}

export function saveTheme(theme: Theme) {
  applyTheme(theme);
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* The choice then lasts only for this page load. */
  }
}

/** Run before the first render so the page never flashes the wrong theme. */
export function initTheme() {
  const os = window.matchMedia("(prefers-color-scheme: dark)");
  applyTheme(savedTheme() ?? (os.matches ? "dark" : "light"));
  os.addEventListener("change", (event) => {
    if (!savedTheme()) applyTheme(event.matches ? "dark" : "light");
  });
}
