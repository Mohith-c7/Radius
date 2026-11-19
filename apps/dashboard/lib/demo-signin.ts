/**
 * Whether the login form offers "Quick Demo Sign-In" (R7). The button signs in with the
 * publicly known credentials of the seeded demo account, so it is shown only in local
 * development: under `next dev`, or in an image built with
 * `NEXT_PUBLIC_RADIUS_DEMO_SIGNIN=true` (set by docker-compose.dev.yml only). Production
 * images run with NODE_ENV=production even in the dev compose stack, so NODE_ENV alone is
 * not the signal. Default: hidden.
 */
export function demoSignInEnabled(flag: string | undefined, nodeEnv: string | undefined): boolean {
  return flag?.trim().toLowerCase() === "true" || nodeEnv === "development";
}
