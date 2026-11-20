import { AppLayout } from "../../components/layout";
import { OrganizationData } from "../../components/data-panels";

export default function OrganizationPage() {
  return (
    <AppLayout>
      <div className="page">
        <OrganizationData />
      </div>
    </AppLayout>
  );
}
