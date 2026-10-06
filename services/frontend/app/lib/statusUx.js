// Tek kaynak durum haritası: tüm sekmeler bunu kullanır.
// Backend'in gerçekten yazdığı TÜM durumları kapsar (_mark çağrıları:
// BLOCKED, SUBMITTING, SUBMITTED, REQUIRES_HUMAN, FILLED, FAILED;
// execute ucu: READY_TO_SUBMIT; orchestrator: READY_TO_APPLY;
// satırda görülen legacy: CREATED, RUNNING, FILLING).
// Bilinmeyen durum nötr rozetle görünür, UI çökmez.
export const STATUS_UX = {
  CREATED: { key: "status.created", next: "prepare", tone: "neutral" },
  DISCOVERED: { key: "status.discovered", next: "prepare", tone: "neutral" },
  RUNNING: { key: "status.running", next: "view", tone: "info" },
  FILLING: { key: "status.filling", next: "view", tone: "info" },
  FILLED: { key: "status.filled", next: "review", tone: "good" },
  SUBMITTING: { key: "status.submitting", next: "view", tone: "info" },
  REQUIRES_HUMAN: { key: "status.requires_human", next: "continue", tone: "warn" },
  READY_TO_SUBMIT: { key: "status.ready", next: "review", tone: "good" },
  READY_TO_APPLY: { key: "status.ready", next: "review", tone: "good" },
  FAILED: { key: "status.failed", next: "retry", tone: "bad" },
  BLOCKED: { key: "status.blocked", next: "open", tone: "warn" },
  SUBMITTED: { key: "status.submitted", next: "details", tone: "done" },
};

export const UNKNOWN_UX = { key: "status.unknown", next: "details", tone: "neutral" };

export function statusUxFor(status) {
  return STATUS_UX[status] || UNKNOWN_UX;
}

// i18n sözlüğünden (STRINGS) yerelleşmiş durum etiketi; sözlükte yoksa ham durum.
export function statusLabel(status, strings) {
  const entry = statusUxFor(status);
  const parts = entry.key.split(".");
  let node = strings;
  for (const part of parts) {
    if (node == null) break;
    node = node[part];
  }
  return typeof node === "string" && node ? node : String(status ?? "UNKNOWN");
}
