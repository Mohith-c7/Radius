import { Suspense } from "react";
import { ForgotPasswordForm } from "../../components/auth-forms";

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<div className="auth-loading">Loading reset link…</div>}>
      <ForgotPasswordForm />
    </Suspense>
  );
}
