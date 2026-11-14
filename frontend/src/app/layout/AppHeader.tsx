import { Link } from "react-router-dom";
import { useAuth } from "../../features/auth/useAuth";
export function AppHeader() {
  const { session, logout } = useAuth();
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Aimo purchasing home">
        aimo<span className="brand-dot">.</span>
      </Link>
      <nav className="product-nav" aria-label="Main navigation">
        <Link to="/">Plan a purchase</Link>
        <Link to="/purchases">Purchases</Link>
      </nav>
      {session && (
        <div className="account">
          <span>{session.buyer_id}</span>
          <button onClick={logout}>Sign out</button>
        </div>
      )}
    </header>
  );
}
