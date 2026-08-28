import { AppLayout } from "../../../components/layout";
import { PullRequestData } from "../../../components/data-panels";

export default async function PullRequestPage({
  params,
}: {
  params: Promise<{ pullRequestId: string }>;
}) {
  const { pullRequestId } = await params;
  return (
    <AppLayout>
      <div className="page">
        <PullRequestData pullRequestId={pullRequestId} />
      </div>
    </AppLayout>
  );
}
