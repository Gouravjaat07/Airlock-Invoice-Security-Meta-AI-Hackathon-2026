/**
 * Invoice intake: invoice (required) + delivery/voice evidence (optional).
 * Retries reuse one idempotency key; the server dedups on it.
 */

import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { createCase } from "../api/endpoints";
import { config } from "../config";
import { FileSlot } from "../components/FileUploader";
import { Button } from "../components/controls";
import { Alert, PageHeader } from "../components/feedback";
import { useToast } from "../components/overlays";

export function IntakePage(): React.JSX.Element {
  const navigate = useNavigate();
  const { notify } = useToast();
  const [invoice, setInvoice] = useState<File | null>(null);
  const [delivery, setDelivery] = useState<File | null>(null);
  const [voice, setVoice] = useState<File | null>(null);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<{ message: string; requestId: string | null } | null>(null);
  // One key per form attempt-series: regenerated only after a confirmed case.
  const keyRef = useRef<string>(crypto.randomUUID());

  const files = [invoice, delivery, voice].filter((f): f is File => f !== null);
  const clientBlocked = invoiceError ?? deliveryError ?? voiceError;
  const canSubmit = invoice !== null && clientBlocked === null && !busy;

  const submit = async (): Promise<void> => {
    if (!canSubmit || !invoice) return;
    setBusy(true);
    setSubmitError(null);
    try {
      const form = new FormData();
      form.append("invoice", invoice, invoice.name);
      if (delivery) form.append("delivery", delivery, delivery.name);
      if (voice) form.append("voice", voice, voice.name);
      const summary = await createCase(form, keyRef.current);
      keyRef.current = crypto.randomUUID();
      notify("Case submitted. Processing starts from the case page.", "success");
      navigate(`/cases/${encodeURIComponent(summary.case.id)}`);
    } catch (error) {
      setSubmitError({
        message: error instanceof ApiError ? error.message : "Submission failed.",
        requestId: error instanceof ApiError ? error.requestId : null,
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="New case"
        description="Upload the invoice and any supporting evidence. Files are treated as untrusted until the pipeline verifies them."
      />
      <div className="ak-card ak-stack" style={{ maxWidth: 720 }}>
        {submitError ? (
          <Alert tone="danger">
            {submitError.message}{" "}
            {submitError.requestId ? <code>ref {submitError.requestId}</code> : null}
          </Alert>
        ) : null}
        <FileSlot
          id="slot-invoice"
          label="Invoice (required)"
          hint={`PDF or image · up to ${config.intake.maxBytesPerFile / 1024 / 1024} MB. `}
          accept={config.intake.invoiceAccept}
          maxBytes={config.intake.maxBytesPerFile}
          value={invoice}
          onChange={(file, error) => {
            setInvoice(file);
            setInvoiceError(error);
          }}
          error={invoiceError}
        />
        <FileSlot
          id="slot-delivery"
          label="Delivery evidence (optional)"
          hint="Photo or MP4 of the delivered goods."
          accept={config.intake.deliveryAccept}
          maxBytes={config.intake.maxBytesPerFile}
          value={delivery}
          onChange={(file, error) => {
            setDelivery(file);
            setDeliveryError(error);
          }}
          error={deliveryError}
        />
        <FileSlot
          id="slot-voice"
          label="Voice note (optional)"
          hint="WAV recording, e.g. spoken delivery confirmation."
          accept={config.intake.voiceAccept}
          maxBytes={config.intake.maxBytesPerFile}
          value={voice}
          onChange={(file, error) => {
            setVoice(file);
            setVoiceError(error);
          }}
          error={voiceError}
        />
        <div>
          <Button variant="primary" loading={busy} disabled={!canSubmit} onClick={() => void submit()}>
            {files.length === 0 ? "Select the invoice to continue" : `Submit ${files.length} file${files.length === 1 ? "" : "s"}`}
          </Button>
          <p className="ak-caption" style={{ marginTop: 10 }}>
            Limits mirror the server defaults ({config.intake.maxFiles} files,{" "}
            {config.intake.maxBytesPerFile / 1024 / 1024} MB each); the backend re-validates
            everything. Retries are safe: one submission key per attempt series.
          </p>
        </div>
      </div>
    </div>
  );
}
