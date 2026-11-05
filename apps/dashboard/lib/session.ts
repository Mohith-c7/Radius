// Server-side session validation for the dashboard (C-01). The dashboard used to
// treat any non-empty `radius_session` cookie as signed in and then called the
// API with the shared server-side key. This module asks the API whether the
// cookie is a live session (GET /api/v1/auth/me) and fails closed on anything
// but a clear "yes". Pure module (no Next.js imports) so it can be unit tested.

export const SESSION_COOKIE = "radius_session";

export type SessionUser = {
  id: string;
  email: string;
  role: string;
  emailVerified: boolean;
};

export type SessionCheck =
  | { ok: true; user: SessionUser }
  | { ok: false; reason: "missing" | "invalid" | "unavailable" };

export type SessionOptions = {
  /** Base URL of the Radius API (no trailing path), same as the proxy uses. */
  apiBaseUrl: string;
  fetchImpl?: typeof fetch;
  now?: () => number;
  /** How long a "signed in" answer is reused (ms). */
  positiveTtlMs?: number;
  /** How long a "rejected" answer is reused (ms). */
  negativeTtlMs?: number;
  timeoutMs?: number;
  cache?: SessionCache;
};

export const POSITIVE_TTL_MS = 15_000;
export const NEGATIVE_TTL_MS = 5_000;
export const VALIDATE_TIMEOUT_MS = 5_000;
const MAX_CACHE_ENTRIES = 500;

type Entry = { result: SessionCheck; expiresAt: number };

export class SessionCache {
  private readonly entries = new Map<string, Entry>();
  // Per-process random key: cache keys are keyed digests, so the raw cookie is
  // never used as a map key and the digest means nothing outside this process.
  private keyPromise: Promise<CryptoKey> | undefined;

  private key(): Promise<CryptoKey> {
    this.keyPromise ??= crypto.subtle.importKey(
      "raw",
      crypto.getRandomValues(new Uint8Array(32)),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    return this.keyPromise;
  }

  async keyFor(cookie: string): Promise<string> {
    const mac = await crypto.subtle.sign("HMAC", await this.key(), new TextEncoder().encode(cookie));
    return Array.from(new Uint8Array(mac), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  get(key: string, now: number): SessionCheck | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt <= now) {
      this.entries.delete(key);
      return undefined;
    }
    return entry.result;
  }

  set(key: string, result: SessionCheck, expiresAt: number): void {
    if (this.entries.size >= MAX_CACHE_ENTRIES) {
      const oldest = this.entries.keys().next().value;
      if (oldest !== undefined) this.entries.delete(oldest);
    }
    this.entries.set(key, { result, expiresAt });
  }

  clear(): void {
    this.entries.clear();
  }
}

export const defaultSessionCache = new SessionCache();

// RFC 6265 cookie-octet: no control characters, whitespace, quote, comma, semicolon or backslash.
const COOKIE_VALUE = /^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]{1,4096}$/;

function parseUser(body: unknown): SessionUser | null {
  if (typeof body !== "object" || body === null) return null;
  const { id, email, role, email_verified: verified } = body as Record<string, unknown>;
  if (typeof id !== "string" || !id || typeof email !== "string" || !email) return null;
  return {
    id,
    email,
    role: typeof role === "string" ? role : "",
    emailVerified: verified === true,
  };
}

/**
 * Validate a session cookie against the API. Only a 200 answer with a user body
 * is "ok"; 401/403 is "invalid"; anything else (network error, timeout, 5xx,
 * malformed body) is "unavailable". Callers must treat both failures as signed out.
 */
export async function validateSession(
  cookieValue: string | undefined,
  options: SessionOptions,
): Promise<SessionCheck> {
  if (!cookieValue) return { ok: false, reason: "missing" };
  if (!COOKIE_VALUE.test(cookieValue)) return { ok: false, reason: "invalid" };
  const now = options.now ?? Date.now;
  const cache = options.cache ?? defaultSessionCache;
  const key = await cache.keyFor(cookieValue);
  const hit = cache.get(key, now());
  if (hit) return hit;

  const doFetch = options.fetchImpl ?? fetch;
  const url = `${options.apiBaseUrl.replace(/\/+$/, "")}/api/v1/auth/me`;
  let result: SessionCheck;
  let cacheTtl = 0;
  try {
    const response = await doFetch(url, {
      method: "GET",
      headers: { Accept: "application/json", Cookie: `${SESSION_COOKIE}=${cookieValue}` },
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(options.timeoutMs ?? VALIDATE_TIMEOUT_MS),
    });
    if (response.status === 401 || response.status === 403) {
      result = { ok: false, reason: "invalid" };
      cacheTtl = options.negativeTtlMs ?? NEGATIVE_TTL_MS;
    } else if (response.status === 200) {
      const user = parseUser(await response.json().catch(() => null));
      if (user) {
        result = { ok: true, user };
        cacheTtl = options.positiveTtlMs ?? POSITIVE_TTL_MS;
      } else {
        result = { ok: false, reason: "unavailable" };
      }
    } else {
      result = { ok: false, reason: "unavailable" };
    }
  } catch {
    result = { ok: false, reason: "unavailable" };
  }
  if (cacheTtl > 0) cache.set(key, result, now() + cacheTtl);
  return result;
}

/** Destructive proxied calls (DELETE) need an admin; everything else any signed-in user. */
export function roleAllows(user: SessionUser, method: string): boolean {
  if (method.toUpperCase() === "DELETE") return user.role === "admin";
  return true;
}
