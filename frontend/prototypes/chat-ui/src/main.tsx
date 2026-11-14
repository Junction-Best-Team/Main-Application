// THROWAWAY prototype entry point. See README.md — not part of the real
// frontend/src/main.tsx app, not built or linted by root CI.
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./theme.css";
import "./style.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
