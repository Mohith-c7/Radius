import { AppLayout } from "../../components/layout";
import { PageHeading } from "../../components/ui";
import { Camera, Github, Mail, ShieldCheck, User } from "lucide-react";

export default function ProfilePage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          title="Account Profile"
          description="Manage your personal details, credentials, and connected developer identity."
          action={
            <button className="button" type="button">
              Save Changes
            </button>
          }
        />

        <div className="detail-grid">
          <section className="card detail-card">
            <div className="profile-heading">
              <span className="profile-avatar">SM</span>
              <div>
                <button className="button secondary" type="button" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <Camera size={14} />
                  Change Avatar
                </button>
              </div>
            </div>
            <h2 style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "16px" }}>
              <User size={18} style={{ color: "var(--green)" }} />
              Personal Information
            </h2>
            <div className="form-grid" style={{ marginTop: "16px" }}>
              <label>
                Full Name
                <input defaultValue="Sanjith Madupalli" className="input" />
              </label>
              <label>
                Email Address
                <input defaultValue="sanjith@radius.dev" type="email" className="input" />
              </label>
              <label>
                Job Title
                <input defaultValue="Staff Software Engineer" className="input" />
              </label>
              <label>
                Timezone
                <select defaultValue="Asia/Kolkata" className="input">
                  <option value="Asia/Kolkata">Asia/Kolkata (IST, UTC+5:30)</option>
                  <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
                  <option value="America/New_York">America/New_York (EST/EDT)</option>
                  <option value="Europe/London">Europe/London (GMT/BST)</option>
                </select>
              </label>
            </div>
          </section>

          <aside className="card detail-card">
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <ShieldCheck size={20} style={{ color: "var(--green)" }} />
              <h2 style={{ margin: 0 }}>Account Access</h2>
            </div>
            <div className="stat-list" style={{ marginTop: "16px" }}>
              <div>
                <span>Workspace Role</span>
                <strong>Admin</strong>
              </div>
              <div>
                <span>Organization</span>
                <strong>Radius Development</strong>
              </div>
              <div>
                <span>Sign-in Method</span>
                <strong>GitHub OAuth</strong>
              </div>
              <div>
                <span>API Tokens</span>
                <strong>1 Active</strong>
              </div>
            </div>
            <a className="text-link" href="/organization" style={{ display: "inline-block", marginTop: "20px" }}>
              Manage organization workspace →
            </a>
          </aside>
        </div>

        <section className="card detail-card wide-card" style={{ marginTop: "24px" }}>
          <h2>Connected Identity</h2>
          <div className="connected-account" style={{ margin: "16px 0" }}>
            <span className="repo-icon">
              <Github size={20} />
            </span>
            <span style={{ display: "grid", gap: "2px" }}>
              <strong>@sanhithamadupalli</strong>
              <small className="muted">Connected via GitHub OAuth for repository access, pull request synchronization, and commit verification.</small>
            </span>
            <button className="button secondary" type="button">
              Re-authenticate
            </button>
          </div>
          <p className="subtext" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <Mail size={14} style={{ color: "var(--muted)" }} />
            Verification summaries and analysis notifications are sent to <strong>sanjith@radius.dev</strong>.
          </p>
        </section>
      </div>
    </AppLayout>
  );
}
