export function apiOriginFrom(value: string | undefined): string;
export function buildCsp(options: {
  nonce: string;
  isDev?: boolean;
  apiOrigin?: string;
  upgradeInsecure?: boolean;
}): string;
export function staticSecurityHeaders(options?: {
  hstsEnabled?: boolean;
}): Array<{ key: string; value: string }>;
export function hstsEnabledFrom(env: Record<string, string | undefined>): boolean;
