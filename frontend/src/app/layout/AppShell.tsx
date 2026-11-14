import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useConversationNavigation } from "../../features/chat/hooks/useConversationNavigation";
import { Wordmark } from "../../shared/components/Wordmark";
import { Icon } from "../../shared/components/DesignPrimitives";
import { UserMenu } from "./UserMenu";

import type { ConversationList } from "../../shared/api/types";
type ConversationListItem = ConversationList["items"][number];

type NavItem = {
  label: string;
  to: string;
  icon: string;
  isActive: (path: string) => boolean;
};

const NAV_ITEMS: NavItem[] = [
  { label: "New request", to: "/", icon: "add", isActive: (p) => p === "/" },
  {
    label: "Requests",
    to: "/request",
    icon: "chat_bubble",
    isActive: (p) => p === "/request" || p.startsWith("/conversations/"),
  },
  {
    label: "Schedule",
    to: "/schedules",
    icon: "calendar_month",
    isActive: (p) => p.startsWith("/schedules"),
  },
  {
    label: "Orders",
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
  `flex min-w-0 flex-1 items-center gap-space-sm rounded-lg px-space-md py-space-sm font-body text-[15px] no-underline transition-colors hover:no-underline ${
    active
      ? "bg-workspace-active text-primary"
      : "text-primary hover:bg-workspace-active"
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
      className="m-0 flex list-none flex-col gap-1 px-space-sm py-space-xs"
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
              <Link
                to={to}
                onClick={onNavigate}
                aria-current={current ? "page" : undefined}
                title={item.title}
                className={`block min-w-0 flex-1 truncate rounded-lg px-space-sm py-space-xs font-body text-body-sm no-underline transition-colors hover:no-underline ${
                  current
                    ? "bg-workspace-active font-semibold text-primary"
                    : "text-primary hover:bg-workspace-active"
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
          </div>
        );
      })}
      {conversations.expanded && (
        <>
          <p className="mb-space-xs mt-space-xl px-space-md text-body-sm text-secondary">
            Recent
          </p>
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
            <p role="alert" className="px-space-md text-body-sm text-error">
              {conversations.error}
            </p>
          )}
        </>
      )}
    </nav>
  );
}

function Sidebar({ conversations }: { conversations: ConversationNav }) {
  // Fixed to the viewport, top to bottom, so it never scrolls with the page;
  // its nav scrolls internally if it outgrows the screen.
  return (
    <aside
      aria-label="Sidebar"
      className="fixed inset-y-0 left-0 z-50 hidden h-dvh w-60 flex-col bg-workspace-panel pb-space-md pt-space-md md:flex"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <Link
          to="/"
          aria-label="aimo. home"
          className="flex h-16 items-center px-space-lg no-underline hover:no-underline"
        >
          <Wordmark className="text-[2.25rem]" />
        </Link>
        <NavLinks conversations={conversations} />
      </div>
    </aside>
  );
}

function DesktopHeader() {
  return (
    <header className="sticky top-0 z-40 hidden h-16 shrink-0 items-center justify-end gap-space-md border-b border-border-subtle bg-surface/80 px-margin backdrop-blur-xl md:flex">
      <UserMenu />
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
    <header className="sticky top-0 z-40 flex h-16 shrink-0 items-center justify-between gap-space-sm border-b border-border-subtle bg-surface/85 px-margin-sm backdrop-blur-xl md:hidden">
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
            Purchasing workspace
          </span>
        </Link>
      </div>
      <UserMenu />
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
        className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col justify-between overflow-y-auto bg-workspace-panel shadow-level-3"
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
          <NavLinks conversations={conversations} onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}

/** Layout route for every signed-in screen. */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  const { pathname } = useLocation();
  const isChat =
    pathname === "/request" || pathname.startsWith("/conversations/");
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
      <div
        className={`flex min-w-0 flex-col md:pl-60 ${isChat ? "h-dvh overflow-hidden" : ""}`}
      >
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
