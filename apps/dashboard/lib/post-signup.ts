import type { AuthUser } from "./auth";

/**
 * Where to send a visitor right after sign-up (or when they open the
 * "Check your email" page). An account that is already verified, for example in
 * local development where DEV_AUTO_VERIFY_EMAIL signs the user in verified, goes
 * straight to the dashboard. "Check your email" is only correct when the API says
 * the address still needs verification.
 */
export function postSignupPath(user: Pick<AuthUser, "email_verified"> | null | undefined): string {
  return user?.email_verified ? "/" : "/verify-email";
}
