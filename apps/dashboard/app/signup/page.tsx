import { Suspense } from "react";
import { SignupForm } from "../../components/auth-forms";

export default function SignupPage() {
  return (
    <Suspense fallback={<div className="auth-loading">Loading sign up…</div>}>
      <SignupForm />
    </Suspense>
  );
}
