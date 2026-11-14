import React from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { store } from "./store";
import { useStoreState } from "./useStoreState";
import { VariantProvider, useVariantNavigate, VLink } from "./variant";
import { VariantBar } from "./VariantBar";
import { Login } from "./Login";
import { ChatPage } from "./ChatPage";
import { PurchasesPage } from "./PurchasesPage";
import { DetailPage } from "./DetailPage";

function Guard({ children }: { children: React.ReactNode }) {
  const { session } = useStoreState();
  const location = useLocation();
  return (
    session ? children : (
      <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
    )
  );
}

function Topbar() {
  const { session } = useStoreState();
  const navigate = useVariantNavigate();
  async function logout() {
    await store.logout();
    navigate("/login", { replace: true });
  }
  return (
    <header className="topbar">
      <VLink to="/" className="brand" aria-label="Aimo purchasing home (prototype)">
        aimo<span className="brand-dot">.</span>
      </VLink>
      <nav className="product-nav" aria-label="Main navigation">
        <VLink to="/">Plan a purchase</VLink>
        <VLink to="/purchases">Purchases</VLink>
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

function Shell() {
  return (
    <VariantProvider>
      <div className="prototype-flag" role="note">
        PROTOTYPE — chat purchasing confirmation UI variants. Fake JSON, nothing here is production.
      </div>
      <Topbar />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/approvals" element={<Navigate to="/purchases" replace />} />
        <Route
          path="/purchases/:proposalId"
          element={
            <Guard>
              <DetailPage />
            </Guard>
          }
        />
        <Route
          path="/approvals/:approvalId"
          element={
            <Guard>
              <DetailPage />
            </Guard>
          }
        />
        <Route
          path="/"
          element={
            <Guard>
              <ChatPage />
            </Guard>
          }
        />
        <Route
          path="/conversations/:conversationId"
          element={
            <Guard>
              <ChatPage />
            </Guard>
          }
        />
        <Route
          path="/purchases"
          element={
            <Guard>
              <PurchasesPage />
            </Guard>
          }
        />
        <Route
          path="*"
          element={
            <main className="workspace">
              <h1>Page not found</h1>
              <VLink to="/">Plan a purchase</VLink>
            </main>
          }
        />
      </Routes>
      <VariantBar />
    </VariantProvider>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}
