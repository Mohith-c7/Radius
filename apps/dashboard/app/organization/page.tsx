import { AppLayout } from "../../components/layout";
import { PageHeading } from "../../components/ui";
import { Mail, MoreHorizontal, Plus, ShieldCheck, Users } from "lucide-react";

interface Member {
  name: string;
  email: string;
  role: string;
  initials: string;
}

const members: Member[] = [
  { name: "Sanjith Madupalli", email: "sanjith@radius.dev", role: "Admin", initials: "SM" },
  { name: "Maya Chen", email: "maya@radius.dev", role: "Developer", initials: "MC" },
  { name: "Jordan Park", email: "jordan@radius.dev", role: "Developer", initials: "JP" },
];

export default function OrganizationPage() {
  return (
    <AppLayout>
      <div className="page">
        <PageHeading
          title="Organization Settings"
          description="Manage workspace members, access controls, and repository verification defaults."
          action={
            <button className="button" type="button">
              <Plus size={15} />
              Invite Member
            </button>
          }
        />

        <div className="detail-grid">
          <section className="card">
            <div className="card-heading">
              <div>
                <h2 style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <Users size={18} style={{ color: "var(--green)" }} />
                  Team Members
                </h2>
                <p>People with access to this Radius workspace</p>
              </div>
            </div>
            <div className="repo-list">
              {members.map((member) => (
                <div className="repo-row" key={member.email}>
                  <span className="avatar">{member.initials}</span>
                  <span>
                    <strong>{member.name}</strong>
                    <small>{member.email}</small>
                  </span>
                  <span className={`status ${member.role === "Admin" ? "active" : "neutral"}`}>
                    {member.role}
                  </span>
                  <button
                    type="button"
                    style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", padding: "4px" }}
                    aria-label={`Options for ${member.name}`}
                  >
                    <MoreHorizontal size={17} />
                  </button>
                </div>
              ))}
            </div>
          </section>

          <aside className="card detail-card" id="defaults">
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <ShieldCheck size={20} style={{ color: "var(--green)" }} />
              <h2 style={{ margin: 0 }}>Verification Defaults</h2>
            </div>
            <p className="muted" style={{ margin: "4px 0 16px", fontSize: "13px" }}>
              Policy rules applied across all monitored repositories.
            </p>
            <div className="stat-list">
              <div>
                <span>Analyze new pull requests</span>
                <strong>Enabled</strong>
              </div>
              <div>
                <span>Publish GitHub checks</span>
                <strong>Enabled</strong>
              </div>
              <div>
                <span>Minimum confidence threshold</span>
                <strong>80 / 100</strong>
              </div>
              <div>
                <span>Coverage floor enforcement</span>
                <strong>Passing tests only</strong>
              </div>
            </div>
            <button className="button secondary" style={{ marginTop: "20px" }} type="button">
              Edit Verification Defaults
            </button>
          </aside>
        </div>

        <section className="card detail-card wide-card" id="access" style={{ marginTop: "24px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
            <Mail size={18} style={{ color: "var(--green)" }} />
            <h2 style={{ margin: 0 }}>Pending Invitations</h2>
          </div>
          <p className="muted" style={{ margin: "0 0 16px" }}>
            Invited members receive an email link to join this workspace and are automatically assigned their role upon sign-in.
          </p>
          <p className="subtext">No pending invitations. All invited members have activated their accounts.</p>
        </section>
      </div>
    </AppLayout>
  );
}
