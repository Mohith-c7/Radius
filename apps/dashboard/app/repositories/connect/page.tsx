import { AppLayout } from "../../../components/layout";
import { ConnectRepositoryForm } from "../../../components/data-panels";

export default function ConnectRepositoryPage() {
  return (
    <AppLayout>
      <div className="page">
        <ConnectRepositoryForm />
      </div>
    </AppLayout>
  );
}
