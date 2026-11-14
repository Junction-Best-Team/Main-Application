import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "../features/auth/AuthProvider";
import { useAuth } from "../features/auth/useAuth";
import { ErrorMessage } from "../shared/components/ErrorMessage";
import { AppShell } from "./layout/AppShell";
import { AppRoutes } from "./AppRoutes";
function AppContent() {
  const { loading, error, session } = useAuth();
  if (loading)
    return (
      <main className="loading" role="status">
        Opening your purchasing workspace…
      </main>
    );
  return (
    <AppShell key={session?.buyer_id ?? "signed-out"}>
      <ErrorMessage message={error} />
      <AppRoutes />
    </AppShell>
  );
}
export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </AuthProvider>
  );
}
