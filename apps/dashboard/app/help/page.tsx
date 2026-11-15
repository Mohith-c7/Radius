import { AppLayout } from "../../components/layout";
import { PageHeading } from "../../components/ui";
import { BookOpen, CircleHelp, ExternalLink, MessageSquare, Search, ShieldCheck } from "lucide-react";

interface HelpArticle {
  title: string;
  detail: string;
  href: string;
}

const articles: HelpArticle[] = [
  {
    title: "Getting started with Radius",
    detail: "Connect your first GitHub repository, configure target branches, and run automated PR verification.",
    href: "https://docs.radius.dev/getting-started",
  },
  {
    title: "How confidence scoring works",
    detail: "Understand how Code Property Graph reachability, test results, and impact depth calculate the heuristic score.",
    href: "https://docs.radius.dev/confidence-model",
  },
  {
    title: "Understanding blast radius & CPG slices",
    detail: "Learn how AST slicing determines affected modules, transitive callers, and targeted test selection.",
    href: "https://docs.radius.dev/blast-radius",
  },
  {
    title: "GitHub App permissions & webhooks",
    detail: "Review why Radius requests read/write repository permissions and how webhook events trigger analysis.",
    href: "https://docs.radius.dev/github-app",
  },
];

export default function HelpPage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          title="Help & Support"
          description="Documentation, developer walkthroughs, and operational support for the Radius platform."
        />

        <section className="card detail-card" style={{ marginBottom: "24px" }}>
          <div className="help-search">
            <Search size={18} style={{ color: "var(--muted)" }} />
            <input
              aria-label="Search help documentation"
              placeholder="Search guides, API docs, CLI commands, and troubleshooting..."
              className="input"
              style={{ border: "none", background: "transparent" }}
            />
          </div>
        </section>

        <div className="help-grid wide-card" style={{ marginBottom: "24px" }}>
          {articles.map((article) => (
            <a
              className="card help-card"
              href={article.href}
              target="_blank"
              rel="noreferrer"
              key={article.title}
            >
              <BookOpen size={18} style={{ color: "var(--green)" }} />
              <h2>{article.title}</h2>
              <p>{article.detail}</p>
              <span className="text-link" style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "13px" }}>
                Read guide <ExternalLink size={13} />
              </span>
            </a>
          ))}
        </div>

        <div className="detail-grid wide-card">
          <section className="card detail-card">
            <MessageSquare size={20} style={{ color: "var(--green)" }} />
            <h2 style={{ marginTop: "12px" }}>Developer Support</h2>
            <p className="muted" style={{ fontSize: "13px", lineHeight: "1.5" }}>
              Have questions about integrating your test suite or interpreting code property graph analysis?
            </p>
            <button className="button" style={{ marginTop: "16px" }} type="button">
              Open Support Ticket
            </button>
          </section>

          <section className="card detail-card">
            <CircleHelp size={20} style={{ color: "var(--green)" }} />
            <h2 style={{ marginTop: "12px" }}>Report an Issue</h2>
            <p className="muted" style={{ fontSize: "13px", lineHeight: "1.5" }}>
              Submit bug reports, unexpected false positives in test selection, or feature requests.
            </p>
            <button className="button secondary" style={{ marginTop: "16px" }} type="button">
              File GitHub Issue
            </button>
          </section>

          <section className="card detail-card">
            <ShieldCheck size={20} style={{ color: "var(--green)" }} />
            <h2 style={{ marginTop: "12px" }}>Platform Health</h2>
            <p className="muted" style={{ fontSize: "13px", lineHeight: "1.5" }}>
              All Radius analysis workers, Celery task queues, and Postgres services are operational.
            </p>
            <a className="text-link" href="#status" style={{ display: "inline-block", marginTop: "16px", fontSize: "13px" }}>
              Check live status page →
            </a>
          </section>
        </div>
      </div>
    </AppLayout>
  );
}
