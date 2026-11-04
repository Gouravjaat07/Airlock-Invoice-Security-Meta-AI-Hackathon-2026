/** Authenticated artifact preview (image/PDF/audio/video from blob URLs). */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { artifactBlob } from "../api/endpoints";
import type { Artifact } from "../api/types";
import { ApiError } from "../api/client";
import { formatBytes } from "../utils/format";
import { safeMessage } from "../utils/errors";
import { FileIcon } from "./icons";

function PreviewBody({ artifact, url }: { artifact: Artifact; url: string }): React.JSX.Element {
  const type = artifact.media_type;
  if (type.startsWith("image/")) {
    return <img src={url} alt={`Artifact ${artifact.id}`} style={{ maxWidth: "100%", borderRadius: 6 }} />;
  }
  if (type === "application/pdf") {
    return (
      <iframe
        src={url}
        title={`Artifact ${artifact.id}`}
        style={{ width: "100%", height: 520, border: "1px solid var(--ak-border)", borderRadius: 6 }}
      />
    );
  }
  if (type.startsWith("audio/")) {
    return <audio src={url} controls style={{ width: "100%" }} />;
  }
  if (type.startsWith("video/")) {
    return <video src={url} controls style={{ width: "100%", borderRadius: 6 }} />;
  }
  return <p className="ak-caption">Preview is not available for {type}.</p>;
}

export function EvidencePreview({ caseId, artifact }: { caseId: string; artifact: Artifact }): React.JSX.Element {
  const [url, setUrl] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["artifact", caseId, artifact.id],
    queryFn: ({ signal }) => artifactBlob(caseId, artifact.id, signal),
    staleTime: Infinity, // blobs are content-addressed and immutable
    retry: false,
  });

  useEffect(() => {
    if (!query.data) return;
    const objectUrl = URL.createObjectURL(query.data);
    setUrl(objectUrl);
    return () => {
      URL.revokeObjectURL(objectUrl);
      setUrl(null);
    };
  }, [query.data]);

  if (query.isPending) {
    return (
      <div aria-label="Loading preview">
        <div className="ak-skeleton" style={{ height: 220 }} />
      </div>
    );
  }
  if (query.isError) {
    const error = query.error;
    return (
      <div className="ak-state" role="alert">
        <span className="ak-state-icon">
          <FileIcon />
        </span>
        <h3>Preview unavailable</h3>
        <p>{safeMessage(error)}</p>
        {error instanceof ApiError && error.requestId ? (
          <p className="ak-caption ak-mono">ref {error.requestId}</p>
        ) : null}
        <div className="ak-state-actions">
          <button type="button" className="ak-btn ak-btn--secondary ak-btn--sm" onClick={() => void query.refetch()}>
            Retry
          </button>
        </div>
      </div>
    );
  }
  return (
    <div>
      {url ? <PreviewBody artifact={artifact} url={url} /> : null}
      <p className="ak-caption" style={{ marginTop: 8 }}>
        {artifact.media_type} · {formatBytes(artifact.size_bytes)} · sha256{" "}
        <span className="ak-mono">{artifact.sha256.slice(0, 16)}…</span>
      </p>
    </div>
  );
}
