import { AppLayout } from "../../components/layout";
import { RepositoriesData } from "../../components/data-panels";

export default function RepositoriesPage() {
  return (
    <AppLayout>
      <div className="page">
        <RepositoriesData />
      </div>
    </AppLayout>
  );
}
