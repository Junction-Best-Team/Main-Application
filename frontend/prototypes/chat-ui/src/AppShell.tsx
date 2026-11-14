// App shell from ui/: left sidebar on desktop (>=768px, Tailwind `md:`), top
// bar + slide-in menu on mobile. Screens render inside <Outlet /> and own
// their <main> landmark and inner layout (e.g. Request adds its own right-hand
// Overview column). Placeholders (search, hub, notifications, help, account)
// are inert and read their content from MOCK.
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { MOCK } from "./mock";
import { Icon, InertButton, InertInput } from "./placeholders";
import { store } from "./store";

type NavItem = { label: string; to: string; icon: string; isActive: (path: string) => boolean };

// Schedule is intentionally absent until its screens exist (spec #81).
export const NAV_ITEMS: NavItem[] = [
  { label: "Home", to: "/", icon: "dashboard", isActive: (p) => p === "/" },
  {
    label: "Request",
    to: "/request",
    icon: "order_approve",
    isActive: (p) => p === "/request" || p.startsWith("/conversations/"),
  },
  {
    label: "Past Orders",
    to: "/purchases",
    icon: "receipt_long",
    isActive: (p) => p.startsWith("/purchases") || p.startsWith("/approvals"),
  },
];

/** Slim mock-data notice shown above every screen, including Login. */
export function NoticeBar() {
  return (
    <div
      role="note"
      className="bg-deep-ocean-navy px-margin-sm py-1 text-center font-label text-label-sm uppercase tracking-wider text-text-on-dark"
    >
      Prototype · mock data only — no real orders are placed
    </div>
  );
}

/** The "aimo." wordmark: Hanken Grotesk 800, deep navy, lime dot. */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`font-headline font-extrabold leading-none tracking-tighter text-deep-ocean-navy ${className}`}>
      aimo<span className="text-status-fresh-green">.</span>
    </span>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  return (
    <nav aria-label="Main navigation" className="flex flex-col gap-space-xs px-space-sm pt-space-sm">
      {NAV_ITEMS.map((item) => {
        const active = item.isActive(pathname);
        return (
          <Link
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-space-sm rounded-lg px-space-md py-space-sm font-label text-label-lg no-underline transition-colors hover:no-underline ${
              active
                ? "bg-primary-container text-on-primary"
                : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
            }`}
          >
            <Icon name={item.icon} className="text-[20px]" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

function HubBadge() {
  return (
    <div className="mx-space-md my-space-sm flex items-center justify-between rounded-lg bg-surface-container-low px-space-sm py-space-xs">
      <span className="flex items-center gap-space-xs font-label text-label-sm uppercase text-on-surface-variant">
        <Icon name="storefront" className="text-[16px] text-wholesale-teal" />
        {MOCK.shell.hub}
      </span>
      <span aria-hidden="true" className="h-2 w-2 rounded-full bg-status-fresh-green" />
    </div>
  );
}

function Avatar() {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary">
      <Icon name="person" className="text-[18px]" />
    </span>
  );
}

/** Account switcher + settings (inert) and the real Sign out action. */
function AccountBlock() {
  const navigate = useNavigate();
  async function logout() {
    await store.logout();
    navigate("/login", { replace: true });
  }
  return (
    <div className="flex flex-col gap-space-xs bg-surface-container-low p-space-sm">
      <InertButton
        label="Switch account"
        className="flex w-full items-center justify-between rounded-lg bg-surface-pure p-space-sm text-left"
      >
        <span className="flex items-center gap-space-sm">
          <Avatar />
          <span className="flex flex-col">
            <span className="font-label text-label-md text-on-surface">{MOCK.shell.account.name}</span>
            <span className="font-label text-label-sm text-on-surface-variant">{MOCK.shell.account.number}</span>
          </span>
        </span>
        <Icon name="unfold_more" className="text-[18px] text-on-surface-variant" />
      </InertButton>
      <InertButton
        label="Account Settings"
        className="flex items-center gap-space-sm px-space-md py-space-sm font-label text-label-md text-on-surface-variant"
      >
        <Icon name="manage_accounts" className="text-[18px]" />
        Account Settings
      </InertButton>
      <button
        type="button"
        onClick={logout}
        className="flex cursor-pointer items-center gap-space-sm rounded-lg border-0 bg-transparent px-space-md py-space-sm font-label text-label-md text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
      >
        <Icon name="logout" className="text-[18px]" />
        Sign out
      </button>
    </div>
  );
}

function NotificationsButton() {
  return (
    <InertButton label="Notifications" className="relative flex h-11 w-11 items-center justify-center text-on-surface-variant">
      <Icon name="notifications" className="text-[22px]" />
      {MOCK.shell.hasUnreadNotifications && (
        <span aria-hidden="true" className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-status-fresh-green" />
      )}
    </InertButton>
  );
}

function Sidebar() {
  // pb-16 keeps the account block clear of the fixed prototype DemoBar.
  return (
    <aside
      aria-label="Sidebar"
      className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col justify-between border-r border-border-subtle bg-surface-pure pb-20 md:flex"
    >
      <div className="flex flex-col">
        <Link to="/" aria-label="aimo. home" className="flex h-16 items-center px-space-lg no-underline hover:no-underline">
          <Wordmark className="text-[2.25rem]" />
        </Link>
        <HubBadge />
        <NavLinks />
      </div>
      <AccountBlock />
    </aside>
  );
}

function DesktopHeader() {
  return (
    <header className="sticky top-0 z-40 hidden h-16 items-center justify-between gap-space-md border-b border-border-subtle bg-surface/80 px-margin backdrop-blur-xl md:flex">
      <div className="relative w-full max-w-xl">
        <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline" />
        <InertInput
          label="Search products"
          placeholder={MOCK.shell.searchPlaceholder}
          className="w-full rounded-lg border border-border-subtle bg-surface-pure py-2 pl-9 pr-space-md font-body text-body-sm text-on-surface placeholder:text-outline"
        />
      </div>
      <div className="flex items-center gap-space-md">
        <div className="flex items-center">
          <NotificationsButton />
          <InertButton label="Help" className="flex h-11 w-11 items-center justify-center text-on-surface-variant">
            <Icon name="help_outline" className="text-[22px]" />
          </InertButton>
        </div>
        <span aria-hidden="true" className="h-5 w-px bg-surface-container-high" />
        <Avatar />
      </div>
    </header>
  );
}

function MobileTopBar({ menuOpen, onOpenMenu }: { menuOpen: boolean; onOpenMenu: () => void }) {
  return (
    <header className="sticky top-0 z-40 flex h-16 items-center justify-between gap-space-sm border-b border-border-subtle bg-surface/85 px-margin-sm backdrop-blur-xl md:hidden">
      <div className="flex items-center gap-space-sm">
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          onClick={onOpenMenu}
          className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-primary hover:bg-surface-container"
        >
          <Icon name="menu" className="text-[24px]" />
        </button>
        <Link to="/" aria-label="aimo. home" className="flex flex-col no-underline hover:no-underline">
          <Wordmark className="text-[1.75rem]" />
          <span className="font-label text-label-sm text-on-surface-variant">{MOCK.shell.hubShort}</span>
        </Link>
      </div>
      <div className="flex items-center gap-space-xs">
        <NotificationsButton />
        <Avatar />
      </div>
    </header>
  );
}

function MobileMenu({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[70] md:hidden">
      <div aria-hidden="true" className="absolute inset-0 bg-deep-ocean-navy/40" onClick={onClose} />
      <div
        id="mobile-menu"
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col justify-between overflow-y-auto bg-surface-pure shadow-level-3"
      >
        <div className="flex flex-col">
          <div className="flex h-16 items-center justify-between px-space-md">
            <Wordmark className="text-[1.75rem]" />
            <button
              type="button"
              aria-label="Close menu"
              onClick={onClose}
              autoFocus
              className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-primary hover:bg-surface-container"
            >
              <Icon name="close" className="text-[24px]" />
            </button>
          </div>
          <HubBadge />
          <NavLinks onNavigate={onClose} />
        </div>
        <AccountBlock />
      </div>
    </div>
  );
}

/** Layout route for every signed-in screen. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setMenuOpen(false), [pathname]);
  return (
    <div className="min-h-screen bg-canvas font-body text-on-surface md:flex">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <DesktopHeader />
        <MobileTopBar menuOpen={menuOpen} onOpenMenu={() => setMenuOpen(true)} />
        <Outlet />
      </div>
      {menuOpen && <MobileMenu onClose={() => setMenuOpen(false)} />}
    </div>
  );
}
