import { Link, Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "../features/auth/components/RequireAuth";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { ChatPage } from "../features/chat/pages/ChatPage";
import { PurchasesPage } from "../features/purchases/pages/PurchasesPage";
import { PurchaseDetailPage } from "../features/purchases/pages/PurchaseDetailPage";
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/approvals" element={<Navigate to="/purchases" replace />} />
      <Route
        path="/purchases/:proposalId"
        element={
          <RequireAuth>
            <PurchaseDetailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/approvals/:approvalId"
        element={
          <RequireAuth>
            <PurchaseDetailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <ChatPage />
          </RequireAuth>
        }
      />
      <Route
        path="/conversations/:conversationId"
        element={
          <RequireAuth>
            <ChatPage />
          </RequireAuth>
        }
      />
      <Route
        path="/purchases"
        element={
          <RequireAuth>
            <PurchasesPage />
          </RequireAuth>
        }
      />
      <Route
        path="*"
        element={
          <main className="workspace">
            <h1>Page not found</h1>
            <Link to="/">Plan a purchase</Link>
          </main>
        }
      />
    </Routes>
  );
}
