import { AppLayout } from "../../components/layout";
import { SettingsPanel } from "../../components/settings-panel";

export default function SettingsPage() {
  return (
    <AppLayout>
      <div className="page">
        <SettingsPanel />
      </div>
    </AppLayout>
  );
}
