import { AppLayout } from "../../components/layout";
import { ServiceStatus } from "../../components/service-status";
import { PageHeading } from "../../components/ui";
import { DOCS_BASE, ISSUES_URL } from "../../lib/dashboard-model";
import { BookOpen, CircleHelp, ExternalLink, MessageSquare, ShieldCheck } from "lucide-react";

const articles = [
  ["Getting started with Radius", "What Radius does, how to run it and connect your first repository.", "README.md"],
  ["How the verdict works", "How Verdict v2 reads evidence per criterion and how the PR comment is laid out.", "docs/verdict-v2.md"],
  ["Uploading CI test results", "Run the selected tests in your CI and upload JUnit XML as evidence.", "docs/CI_INTEGRATION_GUIDE.md"],
  ["Connecting a GitHub repository", "Connect by owner/name through the GitHub App and analyze a pull request without a webhook.", "docs/operations/LIVE_GITHUB_DEMO.md"],
];

const external = { target: "_blank", rel: "noopener noreferrer" } as const;

export default function HelpPage() {
  return <AppLayout><div className="page"><PageHeading eyebrow="Support" title="Help & support" description="Find answers and get help using Radius."/><div className="help-grid wide-card">{articles.map(([title, detail, path])=><a className="card help-card" href={`${DOCS_BASE}/${path}`} {...external} key={title}><BookOpen size={19}/><h2>{title}</h2><p>{detail}</p><span className="text-link">Read article <ExternalLink size={14}/></span></a>)}</div><div className="detail-grid wide-card"><section className="card detail-card"><MessageSquare size={22} color="#19815c"/><h2 style={{marginTop:14}}>Contact support</h2><p className="muted">Need help with your account, an integration, or an analysis result? Open a GitHub issue.</p><a className="button" href={ISSUES_URL} {...external} style={{marginTop:18}}>Contact support</a></section><section className="card detail-card"><CircleHelp size={22} color="#19815c"/><h2 style={{marginTop:14}}>Report an issue</h2><p className="muted">Share a product issue or unexpected verification result with our team.</p><a className="button secondary" href={ISSUES_URL} {...external} style={{marginTop:18}}>Report issue</a></section><section className="card detail-card"><ShieldCheck size={22} color="#19815c"/><h2 style={{marginTop:14}}>Service status</h2><ServiceStatus/><a className="text-link" href={`${DOCS_BASE}/docs/DEPLOYMENT.md`} {...external} style={{marginTop:18}}>Deployment guide <ExternalLink size={14}/></a></section></div></div></AppLayout>;
}
