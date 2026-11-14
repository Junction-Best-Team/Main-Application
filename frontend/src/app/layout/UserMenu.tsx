import { useEffect, useId, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../../features/auth/useAuth";
import { Icon } from "../../shared/components/DesignPrimitives";

/** Header account actions, shared by the desktop and mobile headers. */
export function UserMenu() {
  const { session, logout } = useAuth();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const id = useId();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("a")?.focus();
    const dismissOutside = (event: Event) => {
      if (event.target instanceof Node && !root.current?.contains(event.target))
        setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("focusin", dismissOutside);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("focusin", dismissOutside);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const actionClass = (active = false) =>
    `flex w-full items-center gap-space-sm rounded-lg border-0 px-space-md py-space-sm text-left font-label text-label-md no-underline hover:no-underline ${
      active
        ? "bg-secondary-container text-primary"
        : "bg-transparent text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
    }`;

  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-label="User menu"
        aria-expanded={open}
        aria-controls={id}
        title={`${session?.buyer_id} · ${session?.username}`}
        onClick={() => setOpen((value) => !value)}
        className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full border-0 bg-transparent p-0 hover:bg-surface-container"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-on-primary">
          <Icon name="person" className="text-[18px]" />
        </span>
      </button>
      {open && (
        <nav
          ref={panel}
          id={id}
          aria-label="User account"
          className="absolute right-0 top-full z-50 mt-space-xs w-64 max-w-[calc(100vw-2rem)] rounded-lg border border-primary bg-surface-pure p-space-xs shadow-level-3"
        >
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            aria-current={pathname === "/settings" ? "page" : undefined}
            className={actionClass(pathname === "/settings")}
          >
            <Icon name="manage_accounts" className="text-[18px]" />
            Account Settings
          </Link>
          <Link
            to="/settings/preferences"
            onClick={() => setOpen(false)}
            aria-current={
              pathname.startsWith("/settings/preferences") ? "page" : undefined
            }
            className={actionClass(
              pathname.startsWith("/settings/preferences"),
            )}
          >
            <Icon name="tune" className="text-[18px]" />
            Assistant preferences
          </Link>
          <button
            type="button"
            onClick={logout}
            className={`${actionClass()} cursor-pointer`}
          >
            <Icon name="logout" className="text-[18px]" />
            Sign out
          </button>
        </nav>
      )}
    </div>
  );
}
