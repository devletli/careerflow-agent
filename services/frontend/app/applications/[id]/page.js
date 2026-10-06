"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
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

const LIFECYCLE_OPTIONS = ["DRAFT", "PREPARED", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"];

function DocRow({ doc, appId, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const toggle = async () => {
    setBusy(true);
    setError("");
    try {
      if (doc.linked) {
        await fetchJson(`/api/v1/applications/${appId}/documents/${doc.id}`, {
          method: "DELETE",
        });
      } else {
        await fetchJson(`/api/v1/applications/${appId}/documents`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            document_id: doc.id,
            role: doc.type === "cover_letter" ? "COVER_LETTER" : "CV",
          }),
        });
      }
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <tr>
      <td data-label={STRINGS.colType}>
        {doc.type === "cover_letter" ? "CL" : "CV"}
        <span className="lang-badge">{doc.language.toUpperCase()}</span>
        <span className="lang-badge">v{doc.version}</span>
        {doc.is_latest && <span className="latest-badge">{STRINGS.latestBadge}</span>}
        {doc.linked && <span className="latest-badge">{doc.attached_role || STRINGS.attached}</span>}
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
        {error && <span className="error-banner">{error}</span>}
      </td>
    </tr>
  );
}

function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function LifecyclePanel({ data, id, onChanged }) {
  const [status, setStatus] = useState(data.lifecycle_status || "DRAFT");
  const [method, setMethod] = useState(data.application_method || "AUTOMATED");
  const [nextAction, setNextAction] = useState(data.next_action || "");
  const [dueAt, setDueAt] = useState(toLocalInput(data.next_action_due_at));
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setStatus(data.lifecycle_status || "DRAFT");
    setMethod(data.application_method || "AUTOMATED");
    setNextAction(data.next_action || "");
    setDueAt(toLocalInput(data.next_action_due_at));
  }, [data]);
  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      await fetchJson(`/api/v1/applications/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lifecycle_status: status,
          application_method: method,
          next_action: nextAction,
          next_action_due_at: dueAt ? new Date(dueAt).toISOString() : null,
        }),
      });
      setMessage(STRINGS.saved);
      onChanged();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>{STRINGS.lifecycle}</h3>
      <div className="settings-item">
        <div className="label">{STRINGS.lifecycleStatus}</div>
        <div className="value">
          <StatusPill status={data.lifecycle_status} /> <span className="muted">• {data.application_method}</span>
        </div>
      </div>
      <div className="settings-item">
        <div className="label">{STRINGS.lifecycleStatus}</div>
        <div className="value">
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label={STRINGS.lifecycleStatus}>
            {LIFECYCLE_OPTIONS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="settings-item">
        <div className="label">{STRINGS.applicationMethod}</div>
        <div className="value">
          <select value={method} onChange={(e) => setMethod(e.target.value)} aria-label={STRINGS.applicationMethod}>
            <option value="MANUAL">MANUAL</option>
            <option value="AUTOMATED">AUTOMATED</option>
          </select>
        </div>
      </div>
      <div className="settings-item">
        <div className="label">{STRINGS.appliedAt}</div>
        <div className="value">{data.applied_at ? formatDate(data.applied_at) : "-"}</div>
      </div>
      <div className="settings-item">
        <div className="label">{STRINGS.nextAction}</div>
        <div className="value">
          <input
            value={nextAction}
            onChange={(e) => setNextAction(e.target.value)}
            placeholder={STRINGS.nextActionPlaceholder}
            aria-label={STRINGS.nextAction}
            style={{ width: "100%" }}
          />
        </div>
      </div>
      <div className="settings-item">
        <div className="label">{STRINGS.nextActionDue}</div>
        <div className="value">
          <input
            type="datetime-local"
            value={dueAt}
            onChange={(e) => setDueAt(e.target.value)}
            aria-label={STRINGS.nextActionDue}
          />
        </div>
      </div>
      <button className="refresh-btn primary-btn" onClick={save} disabled={busy}>
        {STRINGS.save}
      </button>
      {message && <div className="action-message">{message}</div>}
    </div>
  );
}

function InterviewsPanel({ interviews, appId, onChanged }) {
  const [form, setForm] = useState({ scheduled_at: "", round: "", mode: "", interviewer: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const create = async () => {
    const hasContent =
      form.scheduled_at ||
      form.round.trim() ||
      form.mode.trim() ||
      form.interviewer.trim() ||
      form.notes.trim();
    if (!hasContent) {
      setMessage(STRINGS.interviewEmpty || "Add a date, round, or notes first.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await fetchJson(`/api/v1/applications/${appId}/interviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          scheduled_at: form.scheduled_at ? new Date(form.scheduled_at).toISOString() : null,
        }),
      });
      setForm({ scheduled_at: "", round: "", mode: "", interviewer: "", notes: "" });
      onChanged();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  };
  const setResult = async (iv, result) => {
    setBusy(true);
    try {
      await fetchJson(`/api/v1/interviews/${iv.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result }),
      });
      onChanged();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (iv) => {
    if (!window.confirm(STRINGS.confirmDeleteInterview)) return;
    setBusy(true);
    try {
      await fetchJson(`/api/v1/interviews/${iv.id}`, { method: "DELETE" });
      onChanged();
    } catch (e) {
      setMessage(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>{STRINGS.interviews}</h3>
      {(interviews || []).length === 0 && <p className="muted">{STRINGS.noInterviews}</p>}
      {(interviews || []).map((iv) => (
        <div key={iv.id} className="settings-item">
          <div className="label">
            {iv.round || "-"} • {iv.scheduled_at ? formatDate(iv.scheduled_at) : STRINGS.unscheduled}
            {iv.mode ? ` • ${iv.mode}` : ""}{iv.interviewer ? ` • ${iv.interviewer}` : ""}
            {iv.notes ? ` — ${iv.notes}` : ""}
          </div>
          <div className="value application-actions">
            <StatusPill status={iv.result} />
            <select
              value={iv.result}
              onChange={(e) => setResult(iv, e.target.value)}
              disabled={busy}
              aria-label={STRINGS.interviewResult}
            >
              {["PENDING", "PASSED", "FAILED", "CANCELLED"].map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <button className="danger-btn" onClick={() => remove(iv)} disabled={busy}>
              {STRINGS.deleteBtn}
            </button>
          </div>
        </div>
      ))}
      <div className="settings-item">
        <div className="label">{STRINGS.scheduleInterview}</div>
      </div>
      <div className="settings-grid">
        <input type="datetime-local" value={form.scheduled_at} onChange={(e) => setForm({ ...form, scheduled_at: e.target.value })} aria-label={STRINGS.interviewDate} />
        <input value={form.round} onChange={(e) => setForm({ ...form, round: e.target.value })} placeholder={STRINGS.interviewRound} aria-label={STRINGS.interviewRound} />
        <input value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} placeholder={STRINGS.interviewMode} aria-label={STRINGS.interviewMode} />
        <input value={form.interviewer} onChange={(e) => setForm({ ...form, interviewer: e.target.value })} placeholder={STRINGS.interviewer} aria-label={STRINGS.interviewer} />
      </div>
      <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} style={{ width: "100%", marginTop: 8 }} placeholder={STRINGS.notes} aria-label={STRINGS.notes} />
      <div style={{ marginTop: 8 }}>
        <button className="refresh-btn primary-btn" onClick={create} disabled={busy}>
          {STRINGS.scheduleInterview}
        </button>
      </div>
      {message && <div className="action-message">{message}</div>}
    </div>
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

  if (loading) return <main className="app-shell"><p className="muted">{STRINGS.loading}</p></main>;
  if (error || !data) {
    return (
      <main className="app-shell">
        <Link className="link" href="/">{STRINGS.backToApplications}</Link>
        <div className="error-banner">{error || id}</div>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <Link className="link" href="/">{STRINGS.backToApplications}</Link>
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
        <div className="stat-card">
          <div className="label">{STRINGS.lifecycle}</div>
          <div className="value"><StatusPill status={data.lifecycle_status} /></div>
        </div>
      </div>

      {data.match && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{data.match.qualification_status}</h3>
          <p className="muted">{data.match.explanation}</p>
        </div>
      )}

      <LifecyclePanel data={data} id={id} onChanged={refresh} />

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{STRINGS.colDocs}</h3>
        {(data.attached_documents || []).length > 0 && (
          <p className="muted">
            {STRINGS.attachedSnapshot}: {(data.attached_documents || []).map((d) => `${d.role} v${d.version}`).join(" • ")}
          </p>
        )}
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
          {["CREATED", "READY_TO_SUBMIT", "READY_TO_APPLY", "FAILED", "REQUIRES_HUMAN"].includes(data.status) && (
            <button className="refresh-btn primary-btn" onClick={() => runAction("fill_applications")}>
              {STRINGS.fillWithPlaywright}
            </button>
          )}
          {["READY_TO_SUBMIT", "READY_TO_APPLY"].includes(data.status) && (
            <button className="refresh-btn primary-btn" onClick={() => runAction("submit_application")}>
              {STRINGS.submitWithPlaywright}
            </button>
          )}
        </div>
        {actionMessage && <div className="action-message">{actionMessage}</div>}
      </div>

      <InterviewsPanel interviews={data.interviews} appId={id} onChanged={refresh} />

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
        {((data.timeline || []).length === 0) && <p className="muted">{STRINGS.noEvents}</p>}
        {(data.timeline || data.events || []).map((e, i) => (
          <div key={e.event_id || `${e.kind}-${i}`} className="settings-item">
            <div className="label">{e.label || e.event_type}</div>
            <div className="value">
              {formatDate(e.timestamp)}
              {e.source ? ` • ${e.source}` : ""}
              {e.note ? ` — ${e.note}` : ""}
            </div>
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
