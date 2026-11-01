import { AppLayout } from "../../../components/layout";
import { AnalysisDetailData } from "../../../components/data-panels";

export default async function AnalysisDetailPage({
  params,
}: {
  params: Promise<{ analysisId: string }>;
}) {
  const { analysisId } = await params;
  return (
    <AppLayout>
      <div className="page">
        <AnalysisDetailData analysisId={analysisId} />
      </div>
    </AppLayout>
  );
}
