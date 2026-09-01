import { Suspense } from "react";
import { VerifyEmailPage } from "../../components/auth-forms";

export default function VerifyEmailRoute() {
  return (
    <Suspense fallback={<div className="auth-loading">Loading email verification…</div>}>
      <VerifyEmailPage />
    </Suspense>
  );
}
