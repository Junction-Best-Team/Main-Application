import { useState } from "react";
import { currentTheme, saveTheme, type Theme } from "../lib/theme";
import { Icon } from "./DesignPrimitives";

/** Switches between the light and dark theme; sits next to the user menu. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>(currentTheme);
  const dark = theme === "dark";
  return (
    <button
      type="button"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
      onClick={() => {
        const next = dark ? "light" : "dark";
        saveTheme(next);
        setTheme(next);
      }}
      className={`flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-on-surface-variant hover:bg-workspace-active hover:text-on-surface ${className}`}
    >
      <Icon name={dark ? "light_mode" : "dark_mode"} className="text-[20px]" />
    </button>
  );
}
