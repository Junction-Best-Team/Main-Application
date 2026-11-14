import { Link } from "react-router-dom";
import { useAuth } from "../../features/auth/useAuth";
export function AppHeader() {
  const { session, logout } = useAuth();
  return (
    <header className="topbar sticky top-0 z-40 flex min-h-20 flex-wrap items-center gap-x-6 gap-y-3 border-b border-border-subtle bg-surface-pure/95 px-4 py-4 backdrop-blur-xl md:px-8">
      <Link
        to="/"
        className="brand font-headline text-[36px] font-extrabold leading-none tracking-[-0.06em] text-deep-ocean-navy hover:no-underline"
        aria-label="Aimo purchasing home"
      >
        aimo<span className="text-status-fresh-green">.</span>
      </Link>
      <nav
        className="product-nav flex flex-wrap items-center gap-1 font-label text-label-md md:ml-5 md:text-label-lg"
        aria-label="Main navigation"
      >
        <Link
          className="rounded-lg px-3 py-2 text-primary hover:bg-surface-container-low hover:no-underline"
          to="/"
        >
          Plan a purchase
        </Link>
        <Link
          className="rounded-lg px-3 py-2 text-primary hover:bg-surface-container-low hover:no-underline"
          to="/purchases"
        >
          Purchases
        </Link>
      </nav>
      {session && (
        <div className="account ml-auto flex min-w-0 items-center gap-4 text-body-sm">
          <span className="max-w-48 truncate text-secondary">
            {session.buyer_id}
          </span>
          <button onClick={logout}>Sign out</button>
        </div>
      )}
    </header>
  );
}
