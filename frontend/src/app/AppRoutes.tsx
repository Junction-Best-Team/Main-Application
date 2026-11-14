import { Link, Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "../features/auth/components/RequireAuth";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { HomePage } from "../features/home/pages/HomePage";
import { ChatPage } from "../features/chat/pages/ChatPage";
import { VoiceModeProvider } from "../features/chat/components/VoiceModeProvider";
import { PurchasesPage } from "../features/purchases/pages/PurchasesPage";
import { PurchaseDetailPage } from "../features/purchases/pages/PurchaseDetailPage";
import { PreferencesPage } from "../features/preferences/pages/PreferencesPage";
import { SettingsPage } from "../features/settings/pages/SettingsPage";
import { AppShell } from "./layout/AppShell";
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/approvals" element={<Navigate to="/purchases" replace />} />
      <Route
        element={
          <RequireAuth>
            <VoiceModeProvider>
              <AppShell />
            </VoiceModeProvider>
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
        <Route path="/settings/preferences" element={<PreferencesPage />} />
      </Route>
      <Route
        path="*"
        element={
          <main className="mx-auto max-w-6xl p-8">
            <h1>Page not found</h1>
            <Link to="/">Go to Home</Link>
          </main>
        }
      />
    </Routes>
  );
}
