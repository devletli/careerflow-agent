"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchJson, formatDate, StatusPill, STRINGS } from "../../lib";

function useDetail(id) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      setData(await fetchJson(`/api/v1/applications/${id}`));
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    refresh();
  }, [refresh]);
  return { data, error, loading, refresh };
}

function DocRow({ doc, appId, onChanged }) {
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      await fetchJson(`/api/v1/applications/${appId}/documents/${doc.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ application_id: doc.linked ? null : appId }),
      });
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr>
      <td data-label={STRINGS.colType}>
        {doc.type === "cover_letter" ? "CL" : "CV"}
        <span className="lang-badge">{doc.language.toUpperCase()}</span>
        {doc.is_latest && <span className="latest-badge">{STRINGS.latestBadge}</span>}
      </td>
      <td data-label={STRINGS.colFile} className="document-actions">
        <a className="link" href={doc.view_url} target="_blank" rel="noreferrer">
          {STRINGS.open}
        </a>
        <a className="link" href={doc.download_url}>
          {STRINGS.download}
        </a>
        <button className="refresh-btn" onClick={toggle} disabled={busy}>
          {doc.linked ? STRINGS.unlink : STRINGS.linkHere}
        </button>
      </td>
    </tr>
  );
}

export default function ApplicationDetail() {
  const { id } = useParams();
  const { data, error, loading, refresh } = useDetail(id);
  const [notes, setNotes] = useState("");
  const [notesMessage, setNotesMessage] = useState("");
  const [actionMessage, setActionMessage] = useState("");

  useEffect(() => {
    if (data) setNotes(data.notes || "");
  }, [data]);

  const saveNotes = async () => {
    setNotesMessage("");
    try {
      await fetchJson(`/api/v1/applications/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes }),
      });
      setNotesMessage(STRINGS.notesSaved);
      refresh();
    } catch (e) {
      setNotesMessage(e.message);
    }
  };

  const runAction = async (action) => {
    const prompt = action === "submit_application" ? STRINGS.confirmSubmit.replace("{name}", data?.title || "") : STRINGS.confirmFill;
    if (action !== "generate_documents" && !window.confirm(prompt)) return;
    setActionMessage("");
    try {
      const body = { action, confirmed: true };
      if (action === "submit_application") body.application_id = id;
      const result = await fetchJson("/api/v1/pipeline/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setActionMessage(result.correlation_id);
      setTimeout(refresh, 1000);
    } catch (e) {
      setActionMessage(e.message);
    }
  };

  if (loading) return <main className="app-shell"><p className="muted">Loading…</p></main>;
  if (error || !data) {
    return (
      <main className="app-shell">
        <a className="link" href="/">{STRINGS.backToApplications}</a>
        <div className="error-banner">{error || id}</div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <a className="link" href="/">{STRINGS.backToApplications}</a>
      <h1>{data.company} — {data.title}</h1>
      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">{STRINGS.colStatus}</div>
          <div className="value"><StatusPill status={data.status} /></div>
        </div>
        <div className="stat-card">
          <div className="label">{STRINGS.colScore}</div>
          <div className="value">{data.match?.overall_score ?? "-"}</div>
        </div>
      </div>

      {data.match && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{data.match.qualification_status}</h3>
          <p className="muted">{data.match.explanation}</p>
        </div>
      )}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{STRINGS.colDocs}</h3>
        {(data.documents || []).length === 0 && <p className="muted">{STRINGS.noDocuments}</p>}
        {(data.documents || []).length > 0 && (
          <table className="responsive">
            <tbody>
              {data.documents.map((d) => (
                <DocRow key={d.id} doc={d} appId={id} onChanged={refresh} />
              ))}
            </tbody>
          </table>
        )}
        <div className="application-actions">
          <button className="refresh-btn primary-btn" onClick={() => runAction("generate_documents")}>
            {STRINGS.regenerate}
          </button>
          <button className="refresh-btn primary-btn" onClick={() => runAction("fill_applications")}>
            {STRINGS.fillWithPlaywright}
          </button>
          <button className="refresh-btn primary-btn" onClick={() => runAction("submit_application")}>
            {STRINGS.submitWithPlaywright}
          </button>
        </div>
        {actionMessage && <div className="action-message">{actionMessage}</div>}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{STRINGS.formAnalysis}</h3>
        {(data.questions || []).length === 0 && <p className="muted">{STRINGS.noQuestions}</p>}
        {(data.questions || []).map((q) => (
          <div key={q.id} className="settings-item">
            <div className="label">{q.text} {q.is_required && `(${STRINGS.required})`}</div>
            <div className="value">
              {q.answer ? `${q.answer.value} (${q.answer.is_verified ? STRINGS.verified : STRINGS.unverified})` : STRINGS.noAnswer}
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{STRINGS.timeline}</h3>
        {(data.events || []).length === 0 && <p className="muted">{STRINGS.noEvents}</p>}
        {(data.events || []).map((e) => (
          <div key={e.event_id} className="settings-item">
            <div className="label">{e.event_type}</div>
            <div className="value">{formatDate(e.timestamp)}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{STRINGS.notes}</h3>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} style={{ width: "100%" }} />
        <button className="refresh-btn primary-btn" onClick={saveNotes}>
          {STRINGS.saveNotes}
        </button>
        {notesMessage && <div className="action-message">{notesMessage}</div>}
      </div>
    </main>
  );
}
