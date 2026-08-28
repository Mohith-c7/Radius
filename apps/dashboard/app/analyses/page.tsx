import { AppLayout } from "../../components/layout";
import { AnalysesData } from "../../components/data-panels";
import { PageHeading } from "../../components/ui";

export default function AnalysesPage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          eyebrow="Verification history"
          title="Analyses"
          description="Every completed and active pull request verification run."
        />
        <AnalysesData />
      </div>
    </AppLayout>
  );
}
