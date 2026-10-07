import { AppLayout } from "../../components/layout";
import { PullRequestsOverviewData } from "../../components/data-panels";
import { PageHeading } from "../../components/ui";

export default function PullRequestsPage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          eyebrow="Continuous Verification"
          title="Pull requests"
          description="Track and inspect pull requests across your connected repositories, their Radius verification statuses, and unique internal IDs."
        />
        <PullRequestsOverviewData />
      </div>
    </AppLayout>
  );
}
