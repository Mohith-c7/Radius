import { AppLayout } from "../../components/layout";
import { TestInsights } from "../../components/test-insights";
import { PageHeading } from "../../components/ui";

export default function TestInsightsPage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          eyebrow="Quality"
          title="Test insights"
          description="Pass rates, flaky tests and recent CI runs from uploaded test results."
        />
        <TestInsights />
      </div>
    </AppLayout>
  );
}
