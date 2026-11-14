import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../../features/auth/useAuth";

type IconName = "truck" | "request" | "receipt" | "menu" | "close" | "person";

function ShellIcon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    truck: (
      <>
        <path d="M3 6h11v11H3zM14 10h4l3 4v3h-7" />
        <circle cx="7" cy="18" r="2" />
        <circle cx="18" cy="18" r="2" />
      </>
    ),
    request: (
      <>
        <path d="M14 3H5v18l3-2 3 2 3-2 3 2v-7M8 7h4M8 11h4M8 15h2M16 3v6m-3-3h6" />
      </>
    ),
    receipt: (
      <>
        <path d="m6 3 3 2 3-2 3 2 3-2v18l-3-2-3 2-3-2-3 2V3ZM9 9h6M9 13h6" />
      </>
    ),
    menu: <path d="M4 6h16M4 12h16M4 18h16" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    person: (
      <>
        <circle cx="12" cy="8" r="3" />
        <path d="M5 21v-3a7 7 0 0 1 14 0v3H5Z" />
      </>
    ),
  };
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

function Brand({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Link
      className="shell-brand"
      to="/"
      onClick={onNavigate}
      aria-label="Valio Aimo home"
    >
      <span className="shell-brand-mark">
        <ShellIcon name="truck" />
      </span>
      <span>
        <strong>Valio Aimo</strong>
        <span className="shell-brand-caption">Wholesale purchasing</span>
      </span>
    </Link>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const requestActive =
    pathname === "/" || pathname.startsWith("/conversations/");
  const purchasesActive = /^\/(purchases|approvals)(\/|$)/.test(pathname);
  return (
    <nav className="shell-nav" aria-label="Main navigation">
      <Link
        to="/"
        onClick={onNavigate}
        aria-current={requestActive ? "page" : undefined}
      >
        <ShellIcon name="request" />
        Request
      </Link>
      <Link
        to="/purchases"
        onClick={onNavigate}
        aria-current={purchasesActive ? "page" : undefined}
      >
        <ShellIcon name="receipt" />
        Purchases
      </Link>
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { session, logout } = useAuth();
  const { pathname } = useLocation();
  const drawer = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const purchasePage = /^\/(purchases|approvals)(\/|$)/.test(pathname);
  const title = purchasePage ? "Purchases" : "Request";

  function closeMenu() {
    drawer.current?.close();
  }

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    function closeOnDesktop() {
      if (desktop.matches) drawer.current?.close();
    }
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  return (
    <div
      className={session ? "app-shell app-shell-authenticated" : "app-shell"}
    >
      <a className="shell-skip" href="#app-content">
        Skip to content
      </a>
      {session && (
        <>
          <aside className="shell-sidebar" aria-label="Application sidebar">
            <Brand />
            <Navigation />
            <div className="shell-sidebar-footer">
              <div className="shell-account">
                <span className="shell-avatar">
                  <ShellIcon name="person" />
                </span>
                <div>
                  <strong>{session.buyer_id}</strong>
                  <span>Buyer account</span>
                </div>
              </div>
              <p>Demo purchasing service</p>
            </div>
          </aside>
          <dialog
            id="app-navigation"
            ref={drawer}
            className="shell-drawer"
            aria-label="Navigation menu"
            onClose={() => setMenuOpen(false)}
            onClick={(event) => {
              if (event.target === event.currentTarget) closeMenu();
            }}
            onKeyDown={(event) => {
              if (event.key !== "Tab") return;
              const controls =
                event.currentTarget.querySelectorAll<HTMLElement>(
                  "a[href], button:not([disabled])",
                );
              const first = controls[0];
              const last = controls[controls.length - 1];
              if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last?.focus();
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first?.focus();
              }
            }}
          >
            <div className="shell-drawer-content">
              <div className="shell-drawer-heading">
                <Brand onNavigate={closeMenu} />
                <button
                  ref={closeButton}
                  type="button"
                  className="shell-icon-button"
                  aria-label="Close navigation"
                  onClick={closeMenu}
                >
                  <ShellIcon name="close" />
                </button>
              </div>
              <Navigation onNavigate={closeMenu} />
              <div className="shell-sidebar-footer">
                <strong>{session.buyer_id}</strong>
                <p>Demo purchasing service</p>
              </div>
            </div>
          </dialog>
        </>
      )}
      <div className="shell-body">
        <header className="shell-header">
          {session && (
            <button
              type="button"
              className="shell-icon-button shell-menu-button"
              aria-label="Open navigation"
              aria-expanded={menuOpen}
              aria-controls="app-navigation"
              onClick={() => {
                drawer.current?.showModal();
                closeButton.current?.focus();
                setMenuOpen(true);
              }}
            >
              <ShellIcon name="menu" />
            </button>
          )}
          <div className={session ? "shell-header-brand" : undefined}>
            <Brand />
          </div>
          {session && (
            <>
              <span className="shell-page-title">{title}</span>
              <div className="shell-header-account">
                <span className="shell-buyer-name">{session.buyer_id}</span>
                <button
                  type="button"
                  className="shell-signout"
                  onClick={logout}
                >
                  Sign out
                </button>
              </div>
            </>
          )}
        </header>
        <div id="app-content" className="shell-content" tabIndex={-1}>
          {children}
        </div>
      </div>
    </div>
  );
}
