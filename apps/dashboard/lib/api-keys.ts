// Fetch helpers for managed API keys. Admin-only: the proxy (lib/proxy.ts)
// forwards the signed-in user's session and the API checks the admin role.
// Tokens returned by create and rotate are shown once and never stored.

import { radiusFetch, type UUID } from "./api";
import {
  ROTATE_OVERLAP_SECONDS,
  createKeyPayload,
  type ApiKey,
  type ApiKeyAuditEvent,
  type ApiKeyCreated,
} from "./api-keys-model";

export function listApiKeys() {
  return radiusFetch<ApiKey[]>("/api-keys");
}

export function listApiKeyAudit() {
  return radiusFetch<ApiKeyAuditEvent[]>("/api-keys/audit");
}

export function createApiKey(name: string, scopes: string[]) {
  return radiusFetch<ApiKeyCreated>("/api-keys", {
    method: "POST",
    body: JSON.stringify(createKeyPayload(name, scopes)),
  });
}

export function rotateApiKey(keyId: UUID) {
  return radiusFetch<ApiKeyCreated>(`/api-keys/${encodeURIComponent(keyId)}/rotate`, {
    method: "POST",
    body: JSON.stringify({ overlap_seconds: ROTATE_OVERLAP_SECONDS }),
  });
}

export function revokeApiKey(keyId: UUID) {
  return radiusFetch<ApiKey>(`/api-keys/${encodeURIComponent(keyId)}`, { method: "DELETE" });
}
