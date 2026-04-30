import { Link } from "react-router-dom";

export default function ForgotPasswordPage() {
  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-semibold">Reset your password</h1>
          <p className="text-sm text-muted-foreground">
            Self-service password reset is coming soon.
          </p>
        </div>

        <div className="rounded-lg border border-border bg-secondary/30 p-5 space-y-3 text-sm">
          <p className="font-medium">How to recover access today:</p>
          <ul className="list-disc pl-5 space-y-2 text-muted-foreground">
            <li>
              <span className="text-foreground">Workspace owners (admins):</span>{" "}
              email <a href="mailto:support@telelytics.org" className="text-primary hover:underline">support@telelytics.org</a> from the address you signed up with. We'll verify
              and reset your password within one business day.
            </li>
            <li>
              <span className="text-foreground">Team members and affiliates:</span>{" "}
              ask your workspace owner to reset your password from
              <span className="font-mono text-xs"> Settings → Team</span> or
              <span className="font-mono text-xs"> Settings → Affiliates</span>.
            </li>
          </ul>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          <Link to="/login" className="text-primary hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
