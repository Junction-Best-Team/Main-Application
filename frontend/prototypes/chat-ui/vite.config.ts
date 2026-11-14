import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Standalone from ../../ (the real app): no backend proxy, no shared
// package.json/lockfile, isolated from CI.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5183,
    // Transform the app on startup so the first page load is not a cold one.
    warmup: { clientFiles: ["./src/main.tsx"] },
  },
  // Pre-bundle every runtime dependency up front, so Vite never discovers one
  // on a first visit and force-reloads the page mid-test.
  optimizeDeps: {
    include: ["react", "react/jsx-dev-runtime", "react-dom/client", "react-router-dom"],
  },
});
