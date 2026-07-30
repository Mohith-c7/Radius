import { AppLayout } from "../../components/layout";
import { PageHeading } from "../../components/ui";
import { BookOpen, CircleHelp, ExternalLink, MessageSquare, Search, ShieldCheck } from "lucide-react";

const articles = [
  ["Getting started with Radius", "Connect a repository and understand your first verification report."],
  ["How confidence scores work", "See how tests, impact, coverage, and dependencies form confidence evidence."],
  ["Understanding blast radius", "Learn how Radius finds affected files, modules, APIs, and tests."],
  ["Managing GitHub App access", "Review repository permissions and your organization’s installation."],
];

export default function HelpPage() {
  return <AppLayout><div className="page"><PageHeading eyebrow="Support" title="Help & support" description="Find answers and get help using Radius."/><section className="card detail-card"><div className="help-search"><Search size={19}/><input aria-label="Search help" placeholder="Search the help center"/></div></section><div className="help-grid wide-card">{articles.map(([title, detail])=><a className="card help-card" href="#article" key={title}><BookOpen size={19}/><h2>{title}</h2><p>{detail}</p><span className="text-link">Read article <ExternalLink size={14}/></span></a>)}</div><div className="detail-grid wide-card"><section className="card detail-card"><MessageSquare size={22} color="#19815c"/><h2 style={{marginTop:14}}>Contact support</h2><p className="muted">Need help with your account, an integration, or an analysis result?</p><button className="button" style={{marginTop:18}}>Contact support</button></section><section className="card detail-card"><CircleHelp size={22} color="#19815c"/><h2 style={{marginTop:14}}>Report an issue</h2><p className="muted">Share a product issue or unexpected verification result with our team.</p><button className="button secondary" style={{marginTop:18}}>Report issue</button></section><section className="card detail-card"><ShieldCheck size={22} color="#19815c"/><h2 style={{marginTop:14}}>Service status</h2><p className="muted">All Radius systems are operating normally.</p><a className="text-link" href="#status" style={{marginTop:18}}>View system status</a></section></div></div></AppLayout>;
}
