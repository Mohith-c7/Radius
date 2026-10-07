import { Suspense } from "react";
import { LoginForm } from "../../components/auth-forms";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="auth-loading">Loading sign in…</div>}>
      <LoginForm />
    </Suspense>
  );
}
