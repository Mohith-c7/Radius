import { AppLayout } from "../../components/layout";
import { CompareData } from "../../components/data-panels";
import { PageHeading } from "../../components/ui";

export default function ComparePage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          eyebrow="Analysis history"
          title="Compare analyses"
          description="Review verification evidence between two backend analysis runs."
        />
        <CompareData />
      </div>
    </AppLayout>
  );
}
