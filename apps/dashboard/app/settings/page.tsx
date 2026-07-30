import { AppLayout } from "../../components/layout";
import { SettingsData } from "../../components/data-panels";

export default function SettingsPage() {
  return (
    <AppLayout>
      <div className="page">
        <SettingsData />
      </div>
    </AppLayout>
  );
}
