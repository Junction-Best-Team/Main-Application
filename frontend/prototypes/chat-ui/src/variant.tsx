import React, { createContext, useContext } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import type { Variant } from "./types";

const VariantContext = createContext<Variant>("sticky");
export const useVariant = () => useContext(VariantContext);

function readVariant(params: URLSearchParams): Variant {
  const raw = params.get("variant");
  return raw === "modal" || raw === "inline" ? raw : "sticky";
}

export function VariantProvider({ children }: { children: React.ReactNode }) {
  const [params] = useSearchParams();
  return <VariantContext.Provider value={readVariant(params)}>{children}</VariantContext.Provider>;
}

function withVariant(path: string, variant: Variant) {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}variant=${variant}`;
}

// A Link that always carries the current ?variant= param, so the switcher
// pins one confirmation pattern while you click around the whole surface.
export function VLink(props: React.ComponentProps<typeof Link>) {
  const [params] = useSearchParams();
  const variant = readVariant(params);
  const to = props.to;
  const path = typeof to === "string" ? to : (to.pathname ?? "");
  return <Link {...props} to={withVariant(path, variant)} />;
}

export function useVariantNavigate() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const variant = readVariant(params);
  return (path: string, opts?: { replace?: boolean }) => navigate(withVariant(path, variant), opts);
}
