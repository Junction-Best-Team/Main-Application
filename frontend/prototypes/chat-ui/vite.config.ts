import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// THROWAWAY prototype config. Fully standalone from ../../ (the real app):
// no backend proxy, no shared package.json/lockfile, isolated from CI.
export default defineConfig({
  plugins: [react()],
  server: { port: 5183 },
});
