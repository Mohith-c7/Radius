import { AppLayout } from "../../../components/layout";
import { RepositoryDetailData } from "../../../components/data-panels";

export default async function RepositoryDetailPage({
  params,
}: {
  params: Promise<{ repositoryId: string }>;
}) {
  const { repositoryId } = await params;
  return (
    <AppLayout>
      <div className="page">
        <RepositoryDetailData repositoryId={repositoryId} />
      </div>
    </AppLayout>
  );
}
