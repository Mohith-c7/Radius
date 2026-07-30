import { AppLayout } from "../components/layout";
import { DashboardOverviewData } from "../components/data-panels";

export default function OverviewPage() {
  return (
    <AppLayout>
      <div className="page">
        <DashboardOverviewData />
      </div>
    </AppLayout>
  );
}
