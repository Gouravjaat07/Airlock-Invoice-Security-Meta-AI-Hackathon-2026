/** Owner PIN login. PIN is never stored; the field clears after submit. */

import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "../auth/session";
import { ApiError } from "../api/client";
import { Button, Field, PinInput } from "../components/controls";
import { Alert } from "../components/feedback";
import { ShieldIcon } from "../components/icons";
import { safeMessage } from "../utils/errors";

export function LoginPage(): React.JSX.Element {
  const { status, expired, login } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "authed") {
    return <Navigate to="/" replace />;
  }

  const showExpired = expired || params.get("expired") === "1";

  const submit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    if (!pin.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(pin);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts. The login is temporarily locked — try again later.");
      } else if (err instanceof ApiError && err.status === 401) {
        setError("Invalid PIN. Check the owner PIN and try again.");
      } else {
        setError(safeMessage(err));
      }
    } finally {
      setPin("");
      setBusy(false);
    }
  };

  return (
    <div className="ak-login-page">
      <div className="ak-login-card">
        <div className="ak-login-brand">
          <span className="ak-brand-mark" aria-hidden="true">
            <ShieldIcon />
          </span>
          <h1 style={{ fontSize: 22 }}>Airlock Console</h1>
        </div>
        <p className="ak-login-sub">
          Owner sign-in for invoice verification, policy review, and mock payment approval.
        </p>
        {showExpired ? (
          <Alert tone="warning">Your session expired. Sign in again to continue.</Alert>
        ) : null}
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <form onSubmit={(e) => void submit(e)} noValidate={false}>
          <Field label="Owner PIN" htmlFor="owner-pin">
            <PinInput
              id="owner-pin"
              value={pin}
              minLength={4}
              maxLength={64}
              required
              disabled={busy}
              onChange={(event) => setPin(event.target.value)}
            />
          </Field>
          <Button type="submit" variant="primary" block loading={busy}>
            Sign in
          </Button>
        </form>
        <p className="ak-login-foot">
          The PIN is verified by the server and never stored in the browser. Sessions expire
          automatically; approval challenges stay in memory only.
        </p>
      </div>
    </div>
  );
}
