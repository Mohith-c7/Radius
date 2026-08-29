export type AuthUser = { id: string; name: string; email: string; email_verified: boolean; role: string };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class AuthError extends Error {}

export async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { credentials: "include", headers: { "Content-Type": "application/json", ...init.headers }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new AuthError(body.detail ?? "We couldn't connect to Radius. Please try again.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const oauthUrl = (provider: "google" | "github") => `${API_URL}/auth/oauth/${provider}`;
