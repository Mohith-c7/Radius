import Link from "next/link";

const analyses = [
  {
    repository: "radius/api",
    pullRequest: "#12",
    status: "Completed",
    confidence: "92%",
    risk: "low"
  },
  {
    repository: "radius/parser",
    pullRequest: "#9",
    status: "Running",
    confidence: "Pending",
    risk: "medium"
  },
  {
    repository: "radius/graph",
    pullRequest: "#7",
    status: "Review",
    confidence: "68%",
    risk: "high"
  }
];

export default function DashboardPage() {
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand">
          <strong>Radius</strong>
          <span>Verification platform</span>
        </div>
        <nav className="nav-list">
          <Link className="nav-item active" href="/">
            Dashboard
          </Link>
          <Link className="nav-item" href="/">
            Repositories
          </Link>
          <Link className="nav-item" href="/">
            Analyses
          </Link>
          <Link className="nav-item" href="/">
            Confidence
          </Link>
        </nav>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>Repository verification</h1>
            <p>Track pull request impact, validation, and merge confidence.</p>
          </div>
          <button className="primary-action" type="button">
            Connect repository
          </button>
        </header>

        <section className="metrics-grid" aria-label="Repository metrics">
          <div className="metric-card">
            <div className="metric-label">Connected repositories</div>
            <div className="metric-value">0</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Active analyses</div>
            <div className="metric-value">0</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Average confidence</div>
            <div className="metric-value">--</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Recent failures</div>
            <div className="metric-value">0</div>
          </div>
        </section>

        <section className="panel" aria-labelledby="recent-analyses">
          <div className="panel-header">
            <div>
              <div className="section-label">Phase 1 foundation</div>
              <h2 id="recent-analyses">Recent analyses</h2>
            </div>
            <span className="table-caption">Sample data</span>
          </div>
          <table className="analysis-table">
            <thead>
              <tr>
                <th>Repository</th>
                <th>Pull request</th>
                <th>Status</th>
                <th>Confidence</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {analyses.map((analysis) => (
                <tr key={`${analysis.repository}-${analysis.pullRequest}`}>
                  <td>{analysis.repository}</td>
                  <td>{analysis.pullRequest}</td>
                  <td>{analysis.status}</td>
                  <td>{analysis.confidence}</td>
                  <td>
                    <span className={`status ${analysis.risk}`}>
                      {analysis.risk}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  );
}
