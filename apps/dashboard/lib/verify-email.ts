/**
 * A-07: in uat/production the account has no password until the mailbox owner chooses one on
 * the verify-email page. The page first asks the API whether a password is needed (the
 * one-time link is not used up by that question), then sends token and password together.
 */

export const PASSWORD_RULE_MESSAGE = "Use at least 8 characters with uppercase, lowercase, and a number.";

/** Same rule as the API (`PASSWORD_PATTERN`). */
export function passwordIsValid(value: string): boolean {
  return /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/.test(value);
}

export type VerifyCheck = { password_required: boolean };

export function isVerifyCheck(value: unknown): value is VerifyCheck {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { password_required?: unknown }).password_required === "boolean"
  );
}

/** Validate the form; returns an error message or null. */
export function validateNewPassword(password: string, confirm: string): string | null {
  if (password !== confirm) return "Passwords do not match.";
  if (!passwordIsValid(password)) return PASSWORD_RULE_MESSAGE;
  return null;
}

/** The body of POST /auth/verify-email: the password is sent only when one is required. */
export function verifyEmailBody(token: string, passwordRequired: boolean, password: string): string {
  return JSON.stringify(passwordRequired ? { token, password } : { token });
}
