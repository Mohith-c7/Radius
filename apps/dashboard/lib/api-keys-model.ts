// Pure helpers for the Settings "API keys" section. No Next.js or fetch
// imports so they can be unit tested with node --test.

/** A managed key as listed by GET /api-keys: prefix only, never the secret. */
export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_by: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  rotated_from_id: string | null;
};

/** POST /api-keys and POST /api-keys/{id}/rotate. `token` is returned once. */
export type ApiKeyCreated = {
  key: ApiKey;
  token: string;
  replaced?: ApiKey | null;
};

/** GET /api-keys/audit. */
export type ApiKeyAuditEvent = {
  id: string;
  api_key_id: string;
  action: string;
  actor: string;
  detail: Record<string, unknown>;
  created_at: string;
};

export const API_KEY_SCOPES = [
  { value: "ci-upload", description: "Upload CI test results only. Use this for CI." },
  { value: "read", description: "Read analyses, verdicts and test results." },
  { value: "write", description: "Read and change data (includes ci-upload)." },
  { value: "admin", description: "Everything, including managing API keys." },
] as const;

export const DEFAULT_KEY_SCOPES = ["ci-upload"];
export const KEY_NAME_MAX = 120;
/** How long a rotated-out key keeps working (the API default). */
export const ROTATE_OVERLAP_SECONDS = 24 * 3600;

export type KeyState = "active" | "expiring" | "expired" | "revoked";

function time(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export function keyState(key: Pick<ApiKey, "expires_at" | "revoked_at">, now = Date.now()): KeyState {
  if (key.revoked_at) return "revoked";
  const expires = time(key.expires_at);
  if (expires === null) return "active";
  return expires <= now ? "expired" : "expiring";
}

/** Only keys that still authenticate can be rotated or revoked. */
export function canManage(key: Pick<ApiKey, "expires_at" | "revoked_at">, now = Date.now()): boolean {
  const state = keyState(key, now);
  return state === "active" || state === "expiring";
}

/** Usable keys first, then newest first. */
export function sortKeys<T extends ApiKey>(keys: T[], now = Date.now()): T[] {
  return [...keys].sort(
    (a, b) =>
      Number(canManage(b, now)) - Number(canManage(a, now)) ||
      (time(b.created_at) ?? 0) - (time(a.created_at) ?? 0) ||
      a.id.localeCompare(b.id),
  );
}

/** Newest first. */
export function sortAudit<T extends ApiKeyAuditEvent>(events: T[]): T[] {
  return [...events].sort(
    (a, b) => (time(b.created_at) ?? 0) - (time(a.created_at) ?? 0) || a.id.localeCompare(b.id),
  );
}

/** Scopes in the canonical order, without duplicates or unknown values. */
export function normalizeScopes(scopes: string[]): string[] {
  const chosen = new Set(scopes);
  return API_KEY_SCOPES.map((scope) => scope.value).filter((value) => chosen.has(value));
}

/** A readable problem with the create form, or null when it can be submitted. */
export function validateKeyForm(name: string, scopes: string[]): string | null {
  const trimmed = name.trim();
  if (!trimmed) return "Give the key a name, for example the repository or CI system that uses it.";
  if (trimmed.length > KEY_NAME_MAX) return `Use at most ${KEY_NAME_MAX} characters for the name.`;
  if (!normalizeScopes(scopes).length) return "Choose at least one scope.";
  return null;
}

export function createKeyPayload(name: string, scopes: string[]): { name: string; scopes: string[] } {
  return { name: name.trim(), scopes: normalizeScopes(scopes) };
}

/** Audit detail as short `key: value` pairs; nested values are summarised, never dumped. */
export function auditDetailText(detail: Record<string, unknown> | null | undefined): string {
  if (!detail) return "";
  return Object.entries(detail)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => {
      if (Array.isArray(value)) return `${key}: ${value.join(", ")}`;
      if (typeof value === "object") return `${key}: ...`;
      return `${key}: ${String(value)}`;
    })
    .join("; ");
}
