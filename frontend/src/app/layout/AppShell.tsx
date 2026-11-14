import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../shared/lib/designPlaceholders";
import { useAuth } from "../../features/auth/useAuth";
import { useConversationNavigation } from "../../features/chat/hooks/useConversationNavigation";
import { NoticeBar } from "../../shared/components/NoticeBar";
import { Wordmark } from "../../shared/components/Wordmark";
import {
  Icon,
  InertButton,
  InertInput,
} from "../../shared/components/DesignPrimitives";

import type { ConversationList } from "../../shared/api/types";
type ConversationListItem = ConversationList["items"][number];

type NavItem = {
  label: string;
  to: string;
  icon: string;
  isActive: (path: string) => boolean;
};

// Schedule is intentionally absent until its screens exist (spec #81).
const NAV_ITEMS: NavItem[] = [
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

type ConversationNav = {
  items: ConversationListItem[] | null;
  expanded: boolean;
  onToggle: () => void;
  loadMore: () => void;
  hasMore: boolean;
  loading: boolean;
  error: string;
};

const navItemClass = (active: boolean) =>
  `flex min-w-0 flex-1 items-center gap-space-sm rounded-lg px-space-md py-space-sm font-label text-label-lg no-underline transition-colors hover:no-underline ${
    active
      ? "bg-primary-container text-on-primary"
      : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
  }`;

/** Collapsible tree of the buyer's conversations under the Request item. */
function ConversationSubList({
  items,
  pathname,
  onNavigate,
}: {
  items: ConversationListItem[] | null;
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <ul
      id="nav-conversations"
      aria-label="Conversations"
      className="m-0 ml-[1.625rem] flex list-none flex-col gap-0.5 border-l border-border-subtle py-space-xs pl-0"
    >
      {!items ? (
        <li className="px-space-md py-space-xs font-body text-body-sm text-on-surface-variant">
          Loading conversations…
        </li>
      ) : (
        items.map((item) => {
          const to = `/conversations/${item.id}`;
          const current = pathname === to;
          return (
            <li key={item.id} className="relative flex">
              <span
                aria-hidden="true"
                className="mt-[1.0625rem] h-px w-space-sm shrink-0 bg-border-subtle"
              />
              <Link
                to={to}
                onClick={onNavigate}
                aria-current={current ? "page" : undefined}
                title={item.title}
                className={`block min-w-0 flex-1 truncate rounded-lg px-space-sm py-space-xs font-body text-body-sm no-underline transition-colors hover:no-underline ${
                  current
                    ? "bg-secondary-container font-bold text-primary"
                    : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                }`}
              >
                {item.title}
              </Link>
            </li>
          );
        })
      )}
    </ul>
  );
}

function NavLinks({
  conversations,
  onNavigate,
}: {
  conversations: ConversationNav;
  onNavigate?: () => void;
}) {
  const { pathname } = useLocation();
  return (
    <nav
      aria-label="Main navigation"
      className="flex flex-col gap-space-xs px-space-sm pt-space-sm"
    >
      {NAV_ITEMS.map((item) => {
        const active = item.isActive(pathname);
        // Request is the current page only for a new request; inside a
        // conversation it marks the current section and the conversation is the page.
        const current = active
          ? item.to === "/request" && pathname !== "/request"
            ? "true"
            : "page"
          : undefined;
        const link = (
          <Link
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            aria-current={current}
            className={navItemClass(active)}
          >
            <Icon name={item.icon} className="text-[20px]" />
            {item.label}
          </Link>
        );
        if (item.to !== "/request") return link;
        return (
          <div key={item.to} className="flex flex-col">
            <div className="flex items-center gap-space-xs">
              {link}
              <button
                type="button"
                aria-expanded={conversations.expanded}
                aria-controls="nav-conversations"
                aria-label={
                  conversations.expanded
                    ? "Hide conversations"
                    : "Show conversations"
                }
                onClick={conversations.onToggle}
                className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
              >
                <Icon
                  name={conversations.expanded ? "expand_less" : "expand_more"}
                  className="text-[20px]"
                />
              </button>
            </div>
            {conversations.expanded && (
              <>
                <ConversationSubList
                  items={conversations.items}
                  pathname={pathname}
                  onNavigate={onNavigate}
                />
                {conversations.hasMore && (
                  <button
                    className="mx-space-md my-space-xs text-label-sm"
                    onClick={conversations.loadMore}
                    disabled={conversations.loading}
                  >
                    Load older conversations
                  </button>
                )}
                {conversations.error && (
                  <p
                    role="alert"
                    className="px-space-md text-body-sm text-error"
                  >
                    {conversations.error}
                  </p>
                )}
              </>
            )}
          </div>
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
        {MOCK.shell.hub} · Placeholder
      </span>
      <span
        aria-hidden="true"
        className="h-2 w-2 rounded-full bg-status-fresh-green"
      />
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

/** Account switcher placeholder, policy settings, assistant preferences and the real Sign out action. */
function AccountBlock({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const { session, logout } = useAuth();
  return (
    <div className="flex shrink-0 flex-col gap-space-xs bg-surface-container-low p-space-sm">
      <InertButton
        label="Switch account"
        className="flex w-full items-center justify-between rounded-lg bg-surface-pure p-space-sm text-left"
      >
        <span className="flex items-center gap-space-sm">
          <Avatar />
          <span className="flex flex-col">
            <span className="font-label text-label-md text-on-surface">
              {session?.buyer_id}
            </span>
            <span className="font-label text-label-sm text-on-surface-variant">
              {session?.username}
            </span>
          </span>
        </span>
        <Icon
          name="unfold_more"
          className="text-[18px] text-on-surface-variant"
        />
      </InertButton>
      <Link
        to="/settings"
        onClick={onNavigate}
        aria-current={pathname === "/settings" ? "page" : undefined}
        className={`flex items-center gap-space-sm rounded-lg px-space-md py-space-sm font-label text-label-md no-underline hover:no-underline ${pathname === "/settings" ? "bg-secondary-container text-primary" : "text-on-surface-variant hover:bg-surface-container-high"}`}
      >
        <Icon name="manage_accounts" className="text-[18px]" />
        Account Settings
      </Link>
      <Link
        to="/settings/preferences"
        onClick={onNavigate}
        aria-current={
          pathname.startsWith("/settings/preferences") ? "page" : undefined
        }
        className={`flex items-center gap-space-sm rounded-lg px-space-md py-space-sm font-label text-label-md no-underline hover:no-underline ${
          pathname.startsWith("/settings/preferences")
            ? "bg-secondary-container text-primary"
            : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
        }`}
      >
        <Icon name="tune" className="text-[18px]" />
        Assistant preferences
      </Link>
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
    <InertButton
      label="Notifications"
      className="relative flex h-11 w-11 items-center justify-center text-on-surface-variant"
    >
      <Icon name="notifications" className="text-[22px]" />
      {MOCK.shell.hasUnreadNotifications && (
        <span
          aria-hidden="true"
          className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-status-fresh-green"
        />
      )}
    </InertButton>
  );
}

function Sidebar({ conversations }: { conversations: ConversationNav }) {
  // Fixed to the viewport, top to bottom, so it never scrolls with the page;
  // its nav scrolls internally if it outgrows the screen. pb-20 keeps the
  // account block clear of the fixed prototype DemoBar.
  return (
    <aside
      aria-label="Sidebar"
      className="fixed inset-y-0 left-0 z-50 hidden h-dvh w-72 flex-col border-r border-border-subtle bg-surface-pure md:flex"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <Link
          to="/"
          aria-label="aimo. home"
          className="flex h-16 items-center px-space-lg no-underline hover:no-underline"
        >
          <Wordmark className="text-[2.25rem]" />
        </Link>
        <HubBadge />
        <NavLinks conversations={conversations} />
      </div>
      <AccountBlock />
    </aside>
  );
}

function DesktopHeader() {
  return (
    <header className="sticky top-0 z-40 hidden h-16 items-center justify-between gap-space-md border-b border-border-subtle bg-surface/80 px-margin backdrop-blur-xl md:flex">
      <div className="relative w-full max-w-xl">
        <Icon
          name="search"
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-outline"
        />
        <InertInput
          label="Search products"
          placeholder={MOCK.shell.searchPlaceholder}
          className="w-full rounded-lg border border-border-subtle bg-surface-pure py-2 pl-9 pr-space-md font-body text-body-sm text-on-surface placeholder:text-outline"
        />
      </div>
      <div className="flex items-center gap-space-md">
        <div className="flex items-center">
          <NotificationsButton />
          <InertButton
            label="Help"
            className="flex h-11 w-11 items-center justify-center text-on-surface-variant"
          >
            <Icon name="help_outline" className="text-[22px]" />
          </InertButton>
        </div>
        <span
          aria-hidden="true"
          className="h-5 w-px bg-surface-container-high"
        />
        <Avatar />
      </div>
    </header>
  );
}

function MobileTopBar({
  menuOpen,
  onOpenMenu,
}: {
  menuOpen: boolean;
  onOpenMenu: () => void;
}) {
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
        <Link
          to="/"
          aria-label="aimo. home"
          className="flex flex-col no-underline hover:no-underline"
        >
          <Wordmark className="text-[1.75rem]" />
          <span className="font-label text-label-sm text-on-surface-variant">
            {MOCK.shell.hubShort} · Demo
          </span>
        </Link>
      </div>
      <div className="flex items-center gap-space-xs">
        <NotificationsButton />
        <Avatar />
      </div>
    </header>
  );
}

function MobileMenu({
  conversations,
  onClose,
}: {
  conversations: ConversationNav;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.querySelector<HTMLButtonElement>(
      'button[aria-controls="mobile-menu"]',
    );
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key !== "Tab") return;
      const items = dialog.current?.querySelectorAll<HTMLElement>(
        "a[href], button:not(:disabled)",
      );
      const first = items?.[0];
      const last = items?.[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement)
        previous.focus({ preventScroll: true });
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[70] md:hidden">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-deep-ocean-navy/40"
        onClick={onClose}
      />
      <div
        ref={dialog}
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
          <NavLinks conversations={conversations} onNavigate={onClose} />
        </div>
        <AccountBlock onNavigate={onClose} />
      </div>
    </div>
  );
}

/** Layout route for every signed-in screen. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const { pathname } = useLocation();
  useEffect(() => setMenuOpen(false), [pathname]);
  const [expanded, setExpanded] = useState(true);
  const navigation = useConversationNavigation(pathname);
  const conversations: ConversationNav = {
    items: navigation.data?.items ?? null,
    loadMore: navigation.loadMore,
    hasMore: navigation.data?.next_offset != null,
    loading: navigation.loading,
    error: navigation.error,
    expanded,
    onToggle: () => setExpanded((open) => !open),
  };
  return (
    <div className="min-h-screen bg-canvas font-body text-on-surface">
      <Sidebar conversations={conversations} />
      <div className="flex min-w-0 flex-col md:pl-72">
        <NoticeBar />
        <DesktopHeader />
        <MobileTopBar
          menuOpen={menuOpen}
          onOpenMenu={() => setMenuOpen(true)}
        />
        <Outlet />
      </div>
      {menuOpen && (
        <MobileMenu conversations={conversations} onClose={closeMenu} />
      )}
    </div>
  );
}
