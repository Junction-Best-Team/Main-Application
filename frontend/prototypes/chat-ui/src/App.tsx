import React, { useEffect } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import { useStoreState } from "./useStoreState";
import { store } from "./store";
import { AppShell, NoticeBar } from "./AppShell";
import { DemoBar } from "./DemoBar";
import { Login } from "./Login";
import { HomePage } from "./HomePage";
import { ChatPage } from "./ChatPage";
import { PurchasesPage } from "./PurchasesPage";

function Guard({ children }: { children: React.ReactNode }) {
  const { session } = useStoreState();
  const location = useLocation();
  return session ? children : <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
}

// Old approval links: resolve the approval to its purchase, then show it in Past Orders.
function ApprovalRedirect() {
  const { approvalId } = useParams();
  const navigate = useNavigate();
  useEffect(() => {
    store
      .getProposal(undefined, approvalId)
      .then((p) => navigate(`/purchases/${p.proposal_id}`, { replace: true }))
      .catch(() => navigate("/purchases", { replace: true }));
  }, [approvalId, navigate]);
  return null;
}

// Routes: Home "/", Request "/request" and "/conversations/:id", Past Orders
// "/purchases" and "/purchases/:id". Every signed-in screen renders inside
// AppShell (sidebar / mobile top bar), which places the notice bar in its
// content column; Login and Not found render the notice bar themselves.
function Shell() {
  return (
    <>
      <Routes>
        <Route
          path="/login"
          element={
            <>
              <NoticeBar />
              <Login />
            </>
          }
        />
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
          <Route path="/purchases" element={<PurchasesPage key="list" />} />
          <Route path="/purchases/:proposalId" element={<PurchasesPage key="deep-link" />} />
          <Route path="/approvals/:approvalId" element={<ApprovalRedirect />} />
        </Route>
        <Route
          path="*"
          element={
            <>
              <NoticeBar />
              <main className="mx-auto flex max-w-[1320px] flex-col gap-space-sm px-[18px] py-7 md:px-10 md:py-12">
                <h1 className="font-headline text-headline-lg-mobile text-primary md:text-headline-lg">
                  Page not found
                </h1>
                <Link to="/" className="font-bold text-wholesale-teal hover:underline">
                  Go to Home
                </Link>
              </main>
            </>
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
