import { useState } from "react";
import { useAuth } from "../../app/AuthContext";
import { ApiError } from "../../api/client";

const demoAccounts = [
  { email: "student@opencs.local", label: "Student" },
  { email: "instructor@opencs.local", label: "Instructor" },
  { email: "admin@opencs.local", label: "Administrator" },
];

export function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("student@opencs.local");
  const [password, setPassword] = useState("opencs-demo");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email.trim().toLowerCase(), password);
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError(cause.message);
      } else {
        setError("Could not sign in. Check your connection and try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background:
          "radial-gradient(1000px 500px at 50% -10%, rgba(91,140,255,0.18), transparent), var(--bg)",
      }}
    >
      <div style={{ width: "100%", maxWidth: 420 }} className="stack">
        <div className="row" style={{ gap: 11, justifyContent: "center", marginBottom: 6 }}>
          <span className="brand-mark" style={{ width: 38, height: 38, fontSize: 19 }}>
            O
          </span>
          <div>
            <div style={{ fontSize: 21, fontWeight: 750, letterSpacing: "-0.4px" }}>OpenCS Labs</div>
            <div className="small dim">Learn · Practise · Analyse</div>
          </div>
        </div>

        <form className="card stack" onSubmit={handleSubmit}>
          <div>
            <h1 style={{ fontSize: 20 }}>Sign in</h1>
            <p className="small muted" style={{ marginBottom: 0 }}>
              Use your course account. Your notebooks and progress stay with you.
            </p>
          </div>

          {error && <div className="notice notice-error">{error}</div>}

          <label className="field">
            <span className="label">Email</span>
            <input
              className="input"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>

          <label className="field">
            <span className="label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
            {submitting ? <span className="spinner" /> : null}
            {submitting ? "Signing in…" : "Sign in"}
          </button>

          <div className="stack-sm">
            <span className="small dim">Demo accounts (development)</span>
            <div className="row" style={{ gap: 6 }}>
              {demoAccounts.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => {
                    setEmail(account.email);
                    setPassword("opencs-demo");
                  }}
                >
                  {account.label}
                </button>
              ))}
            </div>
            <span className="small dim">Password for all demo accounts: opencs-demo</span>
          </div>
        </form>
      </div>
    </div>
  );
}
