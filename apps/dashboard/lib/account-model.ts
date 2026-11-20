// Pure display helpers for the profile and organization pages. They only shape
// what the API already returns (GET /api/v1/auth/me, list pagination meta); they
// never fill in values the backend does not have.

export type AccountUser = {
  name: string;
  email: string;
  email_verified: boolean;
  role: string;
  organization_id?: string | null;
};

export type AccountRow = { label: string; value: string };

/** Up to two initials from the name, else the first letter of the email, else "?". */
export function initials(name: string | null | undefined, email?: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length > 0) {
    return parts
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase();
  }
  const first = (email ?? "").trim()[0];
  return first ? first.toUpperCase() : "?";
}

/** "admin" -> "Admin", "developer" -> "Developer"; an empty role is shown as not set. */
export function roleLabel(role: string | null | undefined): string {
  const text = (role ?? "").trim().replaceAll("_", " ");
  if (!text) return "Not set";
  return text[0].toUpperCase() + text.slice(1);
}

/** The rows of the profile page, all taken from the signed-in user. */
export function profileRows(user: AccountUser): AccountRow[] {
  return [
    { label: "Name", value: user.name.trim() || "Not set" },
    { label: "Email", value: user.email },
    { label: "Email verified", value: user.email_verified ? "Yes" : "No" },
    { label: "Role", value: roleLabel(user.role) },
    { label: "Organization ID", value: user.organization_id || "Not assigned" },
  ];
}

/** `meta.pagination.total` of an API list response, or `fallback` when it is missing or invalid. */
export function paginationTotal(meta: Record<string, unknown> | null | undefined, fallback: number): number {
  const pagination = meta?.pagination;
  if (typeof pagination === "object" && pagination !== null) {
    const total = (pagination as Record<string, unknown>).total;
    if (typeof total === "number" && Number.isInteger(total) && total >= 0) return total;
  }
  return fallback;
}
