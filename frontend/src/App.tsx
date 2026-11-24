import { useState } from "react";

import { useSession } from "./app/useSession";
import { Alert, Button, ErrorBoundary, Tabs } from "./components";
import { AuditPage } from "./features/audit/AuditPage";
import { CasesPage } from "./features/cases/CasesPage";
import { CustomerPage } from "./features/customers/CustomerPage";
import { ResiliencePage } from "./features/resilience/ResiliencePage";
import { Header } from "./layout/Header";
import { StatusBar } from "./layout/StatusBar";
import type { TabId } from "./types/app";
import type { TabItem } from "./types/ui";

const TABS: readonly TabItem<TabId>[] = [
  { id: "cases", label: "Cases", Page: CasesPage },
  { id: "customer", label: "Customer 360", Page: CustomerPage },
  { id: "audit", label: "Audit log", Page: AuditPage },
  { id: "resilience", label: "Resilience lab", Page: ResiliencePage },
];

function SessionGate() {
  const { status, error, retry } = useSession();
  if (status === "error") {
    return (
      <div className="space-y-3">
        <Alert tone="bad">Couldn't sign in: {error}</Alert>
        <Button onClick={retry}>Retry</Button>
      </div>
    );
  }
  return <p className="text-muted">Signing in…</p>;
}

export function App() {
  const { ready, persona } = useSession();
  const [tab, setTab] = useState<TabId>("cases");
  const Page = TABS.find((t) => t.id === tab)?.Page ?? CasesPage;

  return (
    <div className="min-h-screen pb-12">
      <Header />
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      <main className="mx-auto max-w-7xl p-4" role="tabpanel">
        {ready ? (
          // Keyed by persona and tab: switching user or tab remounts the screen and resets any crash state.
          <ErrorBoundary key={`${tab}:${persona ?? ""}`}>
            <Page key={persona} />
          </ErrorBoundary>
        ) : (
          <SessionGate />
        )}
      </main>
      <StatusBar />
    </div>
  );
}
