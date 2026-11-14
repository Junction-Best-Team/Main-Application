import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// THROWAWAY prototype config. Fully standalone from ../../ (the real app):
// no backend proxy, no shared package.json/lockfile, isolated from CI.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5183 },
});
