import React from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useStoreState } from "./useStoreState";
import { AppShell, NoticeBar } from "./AppShell";
import { DemoBar } from "./DemoBar";
import { Login } from "./Login";
import { HomePage } from "./HomePage";
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

// Routes: Home "/", Request "/request" and "/conversations/:id", Past Orders
// "/purchases" and "/purchases/:id". Every signed-in screen renders inside
// AppShell (sidebar / mobile top bar); Login stays outside it.
function Shell() {
  return (
    <>
      <NoticeBar />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/approvals" element={<Navigate to="/purchases" replace />} />
        <Route
          element={
            <Guard>
              <AppShell />
            </Guard>
          }
        >
          <Route path="/" element={<HomePage />} />
          <Route path="/request" element={<ChatPage />} />
          <Route path="/conversations/:conversationId" element={<ChatPage />} />
          <Route path="/purchases" element={<PurchasesPage />} />
          <Route path="/purchases/:proposalId" element={<DetailPage />} />
          <Route path="/approvals/:approvalId" element={<DetailPage />} />
        </Route>
        <Route
          path="*"
          element={
            <main className="workspace">
              <h1>Page not found</h1>
              <Link to="/">Go to Home</Link>
            </main>
          }
        />
      </Routes>
      <DemoBar />
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  );
}
