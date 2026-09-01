import { Suspense } from "react";
import { ResetPasswordForm } from "../../components/auth-forms";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="auth-loading">Loading reset password…</div>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
