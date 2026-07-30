import { AppLayout } from "../../../../components/layout";
import { BlastRadiusData } from "../../../../components/data-panels";

export default async function BlastRadiusPage({
  params,
}: {
  params: Promise<{ analysisId: string }>;
}) {
  const { analysisId } = await params;
  return (
    <AppLayout>
      <div className="page">
        <BlastRadiusData analysisId={analysisId} />
      </div>
    </AppLayout>
  );
}
