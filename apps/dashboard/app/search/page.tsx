import { AppLayout } from "../../components/layout";
import { SearchData } from "../../components/data-panels";
import { PageHeading } from "../../components/ui";

export default function SearchPage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          eyebrow="Analysis discovery"
          title="Search analyses"
          description="Find historical verification runs across repositories."
        />
        <SearchData />
      </div>
    </AppLayout>
  );
}
