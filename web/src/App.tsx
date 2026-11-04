/** Routes: public login, guarded owner console, honest 404. */

import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./auth/session";
import { Shell } from "./layouts/Shell";
import { AuditPage } from "./pages/AuditPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CasesPage } from "./pages/CasesPage";
import { DashboardPage } from "./pages/DashboardPage";
import { IntakePage } from "./pages/IntakePage";
import { LoginPage } from "./pages/LoginPage";
import { ProposalPage } from "./pages/ProposalPage";
import { ProposalsPage } from "./pages/ProposalsPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { SettingsPage } from "./pages/SettingsPage";

function RequireAuth({ children }: { children: React.JSX.Element }): React.JSX.Element {
  const { status, expired } = useSession();
  const location = useLocation();

  if (status === "booting") {
    return (
      <div className="ak-boot" role="status" aria-label="Loading session">
        <div className="ak-boot-inner">
          <span className="ak-spinner" aria-hidden="true" /> Restoring session…
        </div>
      </div>
    );
  }
  if (status === "anon") {
    const search = expired ? "?expired=1" : "";
    return <Navigate to={`/login${search}`} replace state={{ from: location.pathname }} />;
  }
  return children;
}

function NotFound(): React.JSX.Element {
  return (
    <div className="ak-state">
      <h3>Page not found</h3>
      <p>The address does not match any console page.</p>
      <div className="ak-state-actions">
        <Link className="ak-btn ak-btn--secondary ak-btn--sm" to="/">
          Back to overview
        </Link>
      </div>
    </div>
  );
}

export function App(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/new" element={<IntakePage />} />
        <Route path="cases/:caseId" element={<CaseDetailPage />} />
        <Route path="proposals" element={<ProposalsPage />} />
        <Route path="proposals/:proposalId" element={<ProposalPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="providers" element={<ProvidersPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
