import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "../features/auth/AuthProvider";
import { useAuth } from "../features/auth/useAuth";
import { ErrorMessage } from "../shared/components/ErrorMessage";
import { AppRoutes } from "./AppRoutes";
function AppContent() {
  const { loading, error } = useAuth();
  if (loading)
    return (
      <main
        className="loading px-4 py-12 text-center text-secondary"
        role="status"
      >
        Opening your purchasing workspace…
      </main>
    );
  return (
    <>
      <ErrorMessage message={error} />
      <AppRoutes />
    </>
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
