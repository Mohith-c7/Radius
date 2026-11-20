import { AppLayout } from "../../components/layout";
import { SearchData } from "../../components/data-panels";
import { PageHeading } from "../../components/ui";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const { q } = await searchParams;
  const query = (Array.isArray(q) ? q[0] : q) ?? "";
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          eyebrow="Analysis discovery"
          title="Search"
          description="Find pull requests, repositories and verification runs."
        />
        <SearchData initialQuery={query.slice(0, 200)} />
      </div>
    </AppLayout>
  );
}
