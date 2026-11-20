import { AppLayout } from "../../components/layout";
import { ProfileData } from "../../components/data-panels";

export default function ProfilePage() {
  return (
    <AppLayout>
      <div className="page">
        <ProfileData />
      </div>
    </AppLayout>
  );
}
