import { Link, Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "../features/auth/components/RequireAuth";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { HomePage } from "../features/home/pages/HomePage";
import { ChatPage } from "../features/chat/pages/ChatPage";
import { PurchasesPage } from "../features/purchases/pages/PurchasesPage";
import { PurchaseDetailPage } from "../features/purchases/pages/PurchaseDetailPage";
import { SettingsPage } from "../features/settings/pages/SettingsPage";
import { AppShell } from "./layout/AppShell";
import { NoticeBar } from "../shared/components/NoticeBar";
export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <>
            <NoticeBar />
            <LoginPage />
          </>
        }
      />
      <Route path="/approvals" element={<Navigate to="/purchases" replace />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<HomePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/request" element={<ChatPage />} />
        <Route path="/conversations/:conversationId" element={<ChatPage />} />
        <Route path="/purchases" element={<PurchasesPage />} />
        <Route path="/purchases/:proposalId" element={<PurchasesPage />} />
        <Route path="/approvals/:approvalId" element={<PurchaseDetailPage />} />
      </Route>
      <Route
        path="*"
        element={
          <>
            <NoticeBar />
            <main className="mx-auto max-w-6xl p-8">
              <h1>Page not found</h1>
              <Link to="/">Go to Home</Link>
            </main>
          </>
        }
      />
    </Routes>
  );
}
