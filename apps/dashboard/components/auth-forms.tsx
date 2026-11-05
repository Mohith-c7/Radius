"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Check, Eye, EyeOff, Github, LoaderCircle } from "lucide-react";
import { authRequest, oauthUrl, type AuthUser } from "../lib/auth";
import { postSignupPath } from "../lib/post-signup";
import { isVerifyCheck, validateNewPassword, verifyEmailBody } from "../lib/verify-email";
import { useAuth } from "./auth-provider";

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
      />
    </svg>
  );
}

function PasswordField({
  label,
  value,
  onChange,
  id = "password",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  id?: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <label className="auth-label" htmlFor={id}>
      {label}
      <span className="password-input">
        <input
          id={id}
          required
          value={value}
          onChange={(event) => onChange(event.target.value)}
          type={visible ? "text" : "password"}
          autoComplete={id === "password" ? "current-password" : "new-password"}
        />
        <button
          type="button"
          className="password-toggle"
          aria-label={visible ? "Hide password" : "Show password"}
          onClick={() => setVisible(!visible)}
        >
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </span>
    </label>
  );
}

function ProviderButtons({ action = "Continue" }: { action?: string }) {
  return (
    <div className="provider-buttons">
      <a className="provider-button" href={oauthUrl("google")}>
        <GoogleIcon />
        <span>{action} with Google</span>
      </a>
      <a className="provider-button" href={oauthUrl("github")}>
        <Github size={18} />
        <span>{action} with GitHub</span>
      </a>
    </div>
  );
}

function Divider() {
  return (
    <div className="auth-divider">
      <span />
      <span>OR</span>
      <span />
    </div>
  );
}

function Submit({ loading, children }: { loading: boolean; children: string }) {
  return (
    <button className="auth-submit" disabled={loading}>
      {loading && <LoaderCircle className="spin" size={16} />}
      {loading
        ? `${children
            .replace("Sign In", "Signing in")
            .replace("Create Account", "Creating account")
            .replace("Send reset link", "Sending reset link")
            .replace("Reset password", "Resetting password")}…`
        : children}
    </button>
  );
}

function ErrorMessage({ error }: { error: string }) {
  return error ? (
    <p className="auth-error" role="alert">
      {error}
    </p>
  ) : null;
}

function passwordIsValid(value: string) {
  return /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/.test(value);
}

const OAUTH_ERRORS: Record<string, string> = {
  oauth: "We couldn't complete sign in with this provider. Please try again.",
  oauth_denied: "Sign in with the provider was cancelled or denied.",
  oauth_email_unverified: "The provider has not verified your email address. Verify it with the provider and try again.",
  oauth_link_refused:
    "This email already has a Radius account that is not verified, so the provider cannot be linked automatically. Sign in with your password or verify your email first."
};

function oauthErrorMessage(code: string | null): string {
  return code && Object.hasOwn(OAUTH_ERRORS, code) ? OAUTH_ERRORS[code] : "";
}

export function LoginForm() {
  const router = useRouter();
  const query = useSearchParams();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState(oauthErrorMessage(query.get("error")));
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await authRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, remember }),
      });
      await refresh();
      // A full navigation, not router.replace: while signed out the client router may have prefetched
      // "/" and cached the redirect to /login, and a soft navigation would reuse that stale result.
      window.location.assign("/");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "We couldn't connect to Radius. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame title="Welcome back" subtitle="Sign in to your Radius account">
      <ProviderButtons />
      <Divider />
      <form onSubmit={submit} className="auth-form">
        <label className="auth-label">
          Email
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </label>
        <PasswordField label="Password" value={password} onChange={setPassword} />
        <div className="auth-options">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <span>Remember me</span>
          </label>
          <Link href="/forgot-password">Forgot password?</Link>
        </div>
        <ErrorMessage error={error} />
        <Submit loading={loading}>Sign In</Submit>
        <button
          type="button"
          className="button secondary"
          style={{ width: "100%", marginTop: "10px", justifyContent: "center" }}
          onClick={async () => {
            setEmail("demo@radius.dev");
            setPassword("RadiusDemo123!");
            setLoading(true);
            setError("");
            try {
              await authRequest("/auth/login", {
                method: "POST",
                body: JSON.stringify({ email: "demo@radius.dev", password: "RadiusDemo123!", remember: true }),
              });
              await refresh();
              router.replace("/analyses");
            } catch (reason) {
              setError(
                reason instanceof Error
                  ? reason.message
                  : "We couldn't connect to Radius. Please try again."
              );
            } finally {
              setLoading(false);
            }
          }}
        >
          ⚡ Quick Demo Sign-In
        </button>
      </form>
      <AuthFooter prompt="Don't have an account?" href="/signup" action="Create account" />
    </AuthFrame>
  );
}

export function SignupForm() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [terms, setTerms] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const strength = useMemo(
    () =>
      [
        password.length >= 8,
        /[A-Z]/.test(password),
        /[a-z]/.test(password),
        /\d/.test(password),
      ].filter(Boolean).length,
    [password]
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!terms) return setError("Please accept the Terms and Privacy Policy.");
    if (password !== confirm) return setError("Passwords do not match.");
    if (!passwordIsValid(password))
      return setError(
        "Use at least 8 characters with uppercase, lowercase, and a number."
      );
    setLoading(true);
    setError("");
    try {
      const user = await authRequest<AuthUser>("/auth/signup", {
        method: "POST",
        body: JSON.stringify({ name, email, password }),
      });
      await refresh();
      // Already verified (dev auto-verify) -> dashboard; otherwise ask to verify.
      router.replace(postSignupPath(user));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "We couldn't connect to Radius. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame
      title="Create your account"
      subtitle="Start verifying code with Radius"
    >
      <ProviderButtons />
      <Divider />
      <form onSubmit={submit} className="auth-form">
        <label className="auth-label">
          Name
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            maxLength={120}
          />
        </label>
        <label className="auth-label">
          Email
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </label>
        <PasswordField
          label="Password"
          value={password}
          onChange={setPassword}
          id="new-password"
        />
        <div
          className="strength"
          aria-label={`Password strength: ${strength} of 4 requirements`}
        >
          <span className={strength > 0 ? "filled" : ""} />
          <span className={strength > 1 ? "filled" : ""} />
          <span className={strength > 2 ? "filled" : ""} />
          <span className={strength > 3 ? "filled" : ""} />
        </div>
        <p className="field-hint">
          At least 8 characters, uppercase, lowercase, and a number.
        </p>
        <PasswordField
          label="Confirm password"
          value={confirm}
          onChange={setConfirm}
          id="confirm-password"
        />
        <label className="checkbox-label">
          <input
            required
            type="checkbox"
            checked={terms}
            onChange={(e) => setTerms(e.target.checked)}
          />
          <span>
            I agree to the <a href="#terms">Terms</a> and{" "}
            <a href="#privacy">Privacy Policy</a>
          </span>
        </label>
        <ErrorMessage error={error} />
        <Submit loading={loading}>Create Account</Submit>
      </form>
      <AuthFooter
        prompt="Already have an account?"
        href="/login"
        action="Sign in"
      />
    </AuthFrame>
  );
}

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await authRequest("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSent(true);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "We couldn't connect to Radius. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  if (sent)
    return (
      <AuthFrame
        title="Check your email"
        subtitle="If an account exists for this address, we’ve sent a password reset link."
      >
        <div className="auth-success">
          <Check size={20} />
          For your security, we don’t disclose whether an email address is
          registered.
        </div>
        <AuthFooter
          prompt="Remembered your password?"
          href="/login"
          action="Sign in"
        />
      </AuthFrame>
    );

  return (
    <AuthFrame
      title="Reset your password"
      subtitle="Enter your email and we’ll send you a reset link."
    >
      <form className="auth-form" onSubmit={submit}>
        <label className="auth-label">
          Email
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </label>
        <ErrorMessage error={error} />
        <Submit loading={loading}>Send reset link</Submit>
      </form>
      <AuthFooter prompt="Back to" href="/login" action="Sign in" />
    </AuthFrame>
  );
}

export function ResetPasswordForm() {
  const query = useSearchParams();
  const router = useRouter();
  const token = query.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(
    token ? "" : "This reset link is invalid or has expired."
  );
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) return setError("Passwords do not match.");
    if (!passwordIsValid(password))
      return setError(
        "Use at least 8 characters with uppercase, lowercase, and a number."
      );
    setLoading(true);
    setError("");
    try {
      await authRequest("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      setDone(true);
      setTimeout(() => router.replace("/login"), 1500);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "This reset link is invalid or has expired."
      );
    } finally {
      setLoading(false);
    }
  }

  if (done)
    return (
      <AuthFrame
        title="Password reset"
        subtitle="Your password has been updated. Redirecting you to sign in…"
      >
        <div className="auth-success">
          <Check size={20} />
          Your account is ready to use.
        </div>
      </AuthFrame>
    );

  return (
    <AuthFrame
      title="Create a new password"
      subtitle="Choose a strong, unique password for your Radius account."
    >
      <form className="auth-form" onSubmit={submit}>
        <PasswordField
          label="New password"
          value={password}
          onChange={setPassword}
          id="new-password"
        />
        <PasswordField
          label="Confirm new password"
          value={confirm}
          onChange={setConfirm}
          id="confirm-password"
        />
        <ErrorMessage error={error} />
        <Submit loading={loading}>Reset password</Submit>
      </form>
    </AuthFrame>
  );
}

export function VerifyEmailPage() {
  const query = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const [status, setStatus] = useState<"ready" | "loading" | "done" | "error">(
    "ready"
  );
  const token = query.get("token");
  // A-07: null while the API is asked, then whether a password must be chosen here.
  const [passwordRequired, setPasswordRequired] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [formError, setFormError] = useState("");

  // A signed-in, already verified account has nothing to check: go to the dashboard.
  useEffect(() => {
    if (!token && user?.email_verified) router.replace(postSignupPath(user));
  }, [router, token, user]);

  // Ask whether a password is needed; this does not use the one-time link up.
  useEffect(() => {
    if (!token) return;
    let active = true;
    authRequest<unknown>("/auth/verify-email/check", {
      method: "POST",
      body: JSON.stringify({ token }),
    })
      .then((answer) => {
        if (!active) return;
        if (isVerifyCheck(answer)) setPasswordRequired(answer.password_required);
        else setStatus("error");
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => {
      active = false;
    };
  }, [token]);

  async function verify(event?: FormEvent) {
    event?.preventDefault();
    if (!token || passwordRequired === null) return;
    if (passwordRequired) {
      const problem = validateNewPassword(password, confirm);
      if (problem) return setFormError(problem);
    }
    setFormError("");
    setStatus("loading");
    try {
      await authRequest("/auth/verify-email", {
        method: "POST",
        body: verifyEmailBody(token, passwordRequired, password),
      });
      setStatus("done");
    } catch (reason) {
      if (passwordRequired && reason instanceof Error && reason.message) {
        // the link is still usable after a rejected password: show why and let them retry
        setFormError(reason.message);
        setStatus("ready");
      } else {
        setStatus("error");
      }
    }
  }

  async function resend() {
    setStatus("loading");
    try {
      await authRequest("/auth/resend-verification", { method: "POST" });
      setStatus("done");
    } catch {
      setStatus("error");
    }
  }

  if (token)
    return (
      <AuthFrame
        title={status === "done" ? "Email verified" : "Verify your email"}
        subtitle={
          status === "done"
            ? "Your email is verified. You can continue to Radius."
            : passwordRequired
            ? "Confirm your email address and choose the password for your Radius account."
            : "Confirm your email address to secure your Radius account."
        }
      >
        <form className="auth-form" onSubmit={verify}>
          {passwordRequired && status !== "done" && (
            <>
              <PasswordField
                label="Choose a password"
                value={password}
                onChange={setPassword}
                id="new-password"
              />
              <PasswordField
                label="Confirm password"
                value={confirm}
                onChange={setConfirm}
                id="confirm-password"
              />
            </>
          )}
          <ErrorMessage error={formError} />
          <button
            className="auth-submit"
            type="submit"
            disabled={
              status === "loading" ||
              status === "done" ||
              status === "error" ||
              passwordRequired === null
            }
          >
            {status === "done"
              ? "Email verified"
              : status === "loading"
              ? "Verifying…"
              : "Verify email"}
          </button>
        </form>
        {status === "error" && (
          <p className="auth-error" role="alert">
            This verification link is invalid or has expired. Sign in and request a new one.
          </p>
        )}
        <AuthFooter
          prompt="Ready to continue?"
          href="/"
          action="Open dashboard"
        />
      </AuthFrame>
    );

  return (
    <AuthFrame
      title="Check your email"
      subtitle="We’ve sent a verification link to your email address."
    >
      <button
        className="auth-submit"
        onClick={resend}
        disabled={status === "loading"}
      >
        {status === "loading" ? "Sending…" : "Resend verification email"}
      </button>
      {status === "done" && (
        <p className="auth-success">
          <Check size={18} />
          If your address is unverified, a new link has been sent.
        </p>
      )}
      {status === "error" && (
        <p className="auth-error" role="alert">
          We couldn’t send a verification email. Please try again.
        </p>
      )}
      <AuthFooter prompt="Back to" href="/login" action="Sign in" />
    </AuthFrame>
  );
}

function LeftHeroPanel() {
  return (
    <aside className="auth-hero-panel">
      <div className="auth-hero-glow" />
      <div className="auth-hero-content">
        <Link className="auth-brand" href="/">
          <span className="brand-mark">R</span>
          <span className="brand-text">radius</span>
        </Link>

        <div className="auth-hero-body">
          <h2 className="auth-hero-headline">
            Know what your code change affects.
          </h2>

          <p className="auth-hero-subtext">
            Analyze changes, trace dependencies, verify relevant tests, and
            understand merge confidence before your code reaches production.
          </p>

          <div className="verification-card">
            <div className="verification-card-header">
              <div className="verification-badge-group">
                <span className="verification-badge">VERIFICATION</span>
                <span className="pr-chip">PR #1842</span>
              </div>
              <span className="status-live-dot" />
            </div>

            <div className="verification-card-title">
              Update authentication flow
            </div>

            <div className="verification-check-list">
              <div className="verification-check-item">
                <span className="check-bullet">✓</span>
                <span>Tests verified</span>
              </div>
              <div className="verification-check-item">
                <span className="check-bullet">✓</span>
                <span>Dependencies analyzed</span>
              </div>
              <div className="verification-check-item">
                <span className="check-bullet">✓</span>
                <span>Blast radius calculated</span>
              </div>
            </div>

            <div className="verification-card-footer">
              <span className="confidence-title">Confidence</span>
              <div className="confidence-score-badge">
                <span>92%</span>
              </div>
            </div>
          </div>
        </div>

        <div className="auth-hero-footer">
          <span>AI-native verification intelligence</span>
        </div>
      </div>
    </aside>
  );
}

function AuthFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="auth-layout">
      <LeftHeroPanel />
      <section className="auth-form-panel">
        <div className="auth-card">
          <Link className="auth-brand mobile-only-brand" href="/">
            <span className="brand-mark">R</span>
            <span className="brand-text">radius</span>
          </Link>
          <header className="auth-header">
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </header>
          {children}
        </div>
      </section>
    </main>
  );
}

function AuthFooter({
  prompt,
  href,
  action,
}: {
  prompt: string;
  href: string;
  action: string;
}) {
  return (
    <p className="auth-footer">
      {prompt} <Link href={href}>{action}</Link>
    </p>
  );
}
