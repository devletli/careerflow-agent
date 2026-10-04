# CAREERFLOW-AGENT — SENIOR ARCHITECT / DEVOPS / SOFTWARE ENGINEER TASK

Repository:

`https://github.com/devletli/careerflow-agent`

Current branch:

`main`

Known latest major repair commit:

`b1b765af550ebecdd14dd0118df78acb2bf1a684`

You are working as a SENIOR SOFTWARE ARCHITECT + SENIOR BACKEND ENGINEER + SENIOR FRONTEND ENGINEER + DEVOPS ENGINEER.

Do NOT blindly rewrite the project.

First inspect the CURRENT repository state completely.

The project already has a deliberately designed microservice architecture:

Frontend
→ API
→ PostgreSQL
→ Redis Streams
→ workers/services
→ MinIO

The architecture document explicitly defines PostgreSQL as authoritative state and Redis as transport/event infrastructure.

The current system contains:

* FastAPI API
* Next.js frontend
* PostgreSQL
* Redis Streams
* MinIO
* Playwright browser-agent
* job discovery
* matching
* CV/document generation
* application analysis
* application automation
* Docker Compose
* Alembic migrations
* tests
* GitHub Actions CI
* security controls
* correlation IDs
* idempotency
* human-in-the-loop application submission

Do NOT simplify the microservice architecture unless there is a demonstrable technical reason.

For this task, prioritize correctness, maintainability, UI usability, API consistency, data integrity and testability.

---

# 1. FIRST: REPOSITORY AUDIT

Before changing code, inspect at minimum:

```text
README.md
SPEC.md
architecture.md
data-model.md
security.md
docker-compose.yml
pyproject.toml
Makefile

services/api/
services/frontend/
shared/
db/
tests/
.github/workflows/
```

Also inspect:

```text
services/frontend/app/page.js
services/frontend/app/lib.js
services/frontend/app/globals.css

services/frontend/app/components/tabs/JobsTab.js
services/frontend/app/components/tabs/ApplicationsTab.js
services/frontend/app/components/tabs/DocumentsTab.js

services/api/app/main.py
services/api/app/routers/jobs.py
services/api/app/routers/applications_core.py
services/api/app/routers/applications_actions.py
services/api/app/routers/applications_documents.py
services/api/app/routers/documents.py

shared/db/models.py
db/migrations/*
```

Do not assume endpoint names.

Search the entire repository for:

```text
DELETE
@router.delete
fetchJson(
method: "DELETE"
session.delete(
MinIO delete
delete_object
cascade
ondelete
ForeignKey
Document
Application
Job
```

Create a short internal implementation map before editing:

```text
ENTITY
  ↓
FRONTEND COMPONENT
  ↓
FRONTEND ACTION
  ↓
API ENDPOINT
  ↓
SERVICE / DB OPERATION
  ↓
POSTGRES
  ↓
MINIO / REDIS / EVENTS if applicable
  ↓
REFRESH / UI STATE
  ↓
TEST
```

---

# 2. CRITICAL REQUIREMENT: DELETE JOBS

Add a real DELETE operation for Jobs.

The UI currently renders jobs in:

```text
services/frontend/app/components/tabs/JobsTab.js
```

The existing table has:

```jsx
<th>{STRINGS.colLink}</th>
```

and currently ends with:

```jsx
<td data-label={STRINGS.colLink}>
  <a
    className="link"
    href={j.url}
    target="_blank"
    rel="noreferrer"
  >
    {STRINGS.viewLink}
  </a>
</td>
```

This must become an explicit Actions column.

Example target structure:

```jsx
<th>{STRINGS.colActions}</th>
```

and:

```jsx
<td
  data-label={STRINGS.colActions}
  className="actions-sticky"
>
  <a
    className="link"
    href={j.url}
    target="_blank"
    rel="noreferrer"
  >
    {STRINGS.viewLink}
  </a>

  <button
    type="button"
    className="danger-btn"
    onClick={() => onDelete(j)}
    disabled={deletingId === j.id}
  >
    {deletingId === j.id
      ? STRINGS.deleting
      : STRINGS.deleteBtn}
  </button>
</td>
```

BUT:

Do not implement this until the backend DELETE contract has been verified.

Backend should provide:

```http
DELETE /api/v1/jobs/{job_id}
```

Expected behavior:

1. Validate API key.
2. Validate UUID.
3. Find Job.
4. Return 404 if missing.
5. Determine related applications/documents/matches/etc.
6. Apply correct referential deletion policy.
7. Delete associated MinIO artifacts where appropriate.
8. Delete PostgreSQL records safely.
9. Commit transaction.
10. Return a deterministic response.
11. Never leave orphaned DB or MinIO artifacts.
12. Never delete another unrelated job's documents.

Preferred response:

```json
{
  "id": "JOB_UUID",
  "deleted": true
}
```

or HTTP `204 No Content`.

Choose ONE convention and use it consistently for all delete endpoints.

---

# 3. CRITICAL REQUIREMENT: DELETE APPLICATIONS

Applications currently have sophisticated state-based actions:

```text
CREATED
READY_TO_SUBMIT
RUNNING
FILLING
SUBMITTING
REQUIRES_HUMAN
BLOCKED
FAILED
SUBMITTED
```

Do NOT break this state machine.

The existing `ApplicationsTab.js` contains:

```jsx
function getAvailableActions(application) {
  switch (application.status) {
    case "CREATED":
      return ["prepare"];

    case "READY_TO_SUBMIT":
    case "READY_TO_APPLY":
      return ["submit"];

    case "RUNNING":
    case "FILLING":
    case "SUBMITTING":
      return ["view"];

    case "REQUIRES_HUMAN":
    case "BLOCKED":
      return ["continue"];

    case "FAILED":
      return ["retry"];

    case "SUBMITTED":
      return ["details"];

    default:
      return [];
  }
}
```

Add delete independently from this state-machine action list.

Do NOT make delete depend on `getAvailableActions()`.

Add:

```jsx
<button
  type="button"
  className="danger-btn"
  onClick={() => onDelete(a)}
  disabled={busyId === a.id}
>
  {STRINGS.deleteBtn}
</button>
```

However, deleting an application requires backend support.

Implement:

```http
DELETE /api/v1/applications/{application_id}
```

Rules:

* 404 if application does not exist.
* Delete only the requested application.
* Do not accidentally delete the Job.
* Handle related ApplicationQuestion records.
* Handle ApplicationAnswer records.
* Handle AutomationRun records.
* Handle application-related events correctly.
* Handle linked Documents according to the actual DB model.
* Do not delete documents belonging to another application.
* Clean up MinIO artifacts only when ownership/reference rules say they are no longer needed.
* Preserve job data unless the Job itself is explicitly deleted.
* Do not publish misleading `application.submitted` or other business events when deleting.
* If an audit/event record must remain, preserve an appropriate deletion/audit record rather than destroying the entire audit trail blindly.

IMPORTANT:

Before implementing cascade deletion, inspect:

```text
shared/db/models.py
```

and all foreign keys.

Do not invent cascade behavior.

---

# 4. CRITICAL REQUIREMENT: DELETE DOCUMENTS

Current Documents UI:

```text
services/frontend/app/components/tabs/DocumentsTab.js
```

currently renders:

```jsx
<td data-label={STRINGS.colFile} className="document-actions">
  <a
    className="link"
    href={document.view_url}
    target="_blank"
    rel="noreferrer"
  >
    {STRINGS.viewFile}
  </a>
</td>
```

Add:

```jsx
<button
  type="button"
  className="danger-btn"
  onClick={() => onDelete(document)}
  disabled={deletingId === document.id}
>
  {deletingId === document.id
    ? STRINGS.deleting
    : STRINGS.deleteBtn}
</button>
```

Backend:

```http
DELETE /api/v1/documents/{document_id}
```

This is especially important because Documents are not just DB rows.

They contain MinIO storage information such as:

```text
document.minio_key
document.minio_bucket
```

The existing backend explicitly uses MinIO to stream private artifacts.

Therefore document deletion MUST be:

```text
validate document
      ↓
identify MinIO object
      ↓
delete DB record safely
      ↓
delete MinIO object
      ↓
commit / rollback correctly
```

Do NOT leave orphaned MinIO files.

Also do NOT delete the MinIO object first without thinking about transaction failure.

Design the deletion sequence carefully.

If DB transaction succeeds but MinIO deletion fails, do NOT silently claim everything was deleted.

Use the project's existing error/logging conventions.

---

# 5. VERY IMPORTANT: DOCUMENT VERSIONING

The current Documents endpoint deliberately returns only the latest document per:

```text
(job_id, type, language)
```

The backend calculates latest versions.

The UI filters:

```jsx
const rows = (documents || []).filter((d) => d.is_latest);
```

Do not break this.

Before deleting a document, determine:

```text
Is it latest?
Is it referenced by an application?
Is it an old version?
Does another document depend on it?
Does the DB store artifact metadata?
```

Deletion must respect the document version model.

Do not blindly delete every version when the user clicks delete on one document.

---

# 6. CASCADE POLICY

Do NOT blindly use:

```python
cascade="all, delete-orphan"
```

everywhere.

Do not add broad:

```text
ON DELETE CASCADE
```

without checking business semantics.

Use this conceptual model:

```text
JOB
 ├── JobMatch
 ├── JobRequirement
 ├── Documents
 └── Applications
       ├── Questions
       ├── Answers
       ├── AutomationRuns
       └── application-related records
```

The correct deletion policy must be derived from the actual models.

For Job deletion, determine whether:

```text
Job → Application
```

should cascade.

If yes:

```text
DELETE JOB
  → delete applications
  → delete application questions
  → delete application answers
  → delete automation runs
  → delete documents
  → delete MinIO artifacts
  → delete matches/requirements
  → delete job
```

If the existing architecture intentionally preserves some historical records, implement that instead.

The source of truth is the existing data model, not assumptions.

---

# 7. FRONTEND DELETE UX

Do NOT use ugly browser-native confirmation everywhere if a reusable project pattern exists.

If the project has no reusable modal, implement a small reusable confirmation component.

Example:

```jsx
function ConfirmDeleteDialog({
  open,
  title,
  message,
  onCancel,
  onConfirm,
  loading,
}) {
  if (!open) return null;

  return (
    <div className="modal-backdrop">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
      >
        <h3>{title}</h3>

        <p>{message}</p>

        <div className="modal-actions">
          <button
            type="button"
            className="refresh-btn"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </button>

          <button
            type="button"
            className="danger-btn"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

Do NOT hard-code these strings in components.

The project already has:

```text
services/frontend/i18n/en.json
services/frontend/i18n/tr.json
```

and `lib.js` exposes:

```jsx
export const STRINGS = LOCALE === "tr"
  ? trStrings
  : enStrings;
```

Therefore add:

```json
{
  "deleteBtn": "Delete",
  "deleting": "Deleting…",
  "cancelBtn": "Cancel",
  "confirmDeleteJob": "Delete this job?",
  "confirmDeleteApplication": "Delete this application?",
  "confirmDeleteDocument": "Delete this document?",
  "deleteJobDescription": "This will permanently remove the job and its dependent data.",
  "deleteApplicationDescription": "This will permanently remove the application and its dependent application data.",
  "deleteDocumentDescription": "This will permanently remove the document and its stored artifact."
}
```

and equivalent Turkish translations.

Do not introduce hard-coded user-visible English text.

---

# 8. DO NOT ALLOW DOUBLE DELETE

Frontend must prevent:

```text
double click
multiple DELETE requests
race condition
stale UI
```

Example:

```jsx
const [deletingId, setDeletingId] = useState(null);

async function handleDelete(item) {
  if (!item?.id || deletingId) return;

  setDeletingId(item.id);

  try {
    await fetchJson(`/api/v1/.../${item.id}`, {
      method: "DELETE",
    });

    await refresh();
  } finally {
    setDeletingId(null);
  }
}
```

Improve this with proper error handling.

Never silently swallow DELETE failures.

---

# 9. IMPORTANT: REFRESH ALL DEPENDENT DATA

After deleting a Job:

```text
jobsQ.refresh()
applicationsQ.refresh()
documentsQ.refresh()
eventsQ.refresh()
```

if those datasets can be affected.

After deleting an Application:

```text
applicationsQ.refresh()
documentsQ.refresh()
eventsQ.refresh()
```

if applicable.

After deleting a Document:

```text
documentsQ.refresh()
applicationsQ.refresh()
```

if document counts/badges are displayed in applications.

The current `page.js` already has polling objects:

```jsx
const jobsQ = usePolling(...)
const applicationsQ = usePolling(...)
const documentsQ = usePolling(...)
const eventsQ = usePolling(...)
```

Use these existing mechanisms.

Do not create a second state-management architecture.

---

# 10. UI TABLE WIDTH / SCROLL PROBLEM

The previous work introduced:

```css
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.tab-panel {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.table-wrapper {
  height: 100%;
  min-height: 0;
  overflow: auto;
}

.table-fixed {
  width: 100%;
  table-layout: fixed;
}

.cell-truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions-sticky {
  position: sticky;
  right: 0;
  z-index: 10;
}
```

Do NOT simply remove these.

The intent is:

* tabs stay within viewport
* tables fit available width
* action column remains visible
* long text truncates
* scrolling happens only where necessary

However, verify the implementation visually and structurally.

The Applications table MUST NOT require horizontal scrolling just because the Actions column was added.

Use controlled column widths.

Example:

```css
.table-fixed th:nth-child(1) { width: 28%; }
.table-fixed th:nth-child(2) { width: 8%; }
.table-fixed th:nth-child(3) { width: 12%; }
.table-fixed th:nth-child(4) { width: 12%; }
.table-fixed th:nth-child(5) { width: 12%; }
.table-fixed th:nth-child(6) { width: 28%; }
```

Adjust based on the actual columns.

Do NOT blindly use these percentages.

For Jobs:

```text
Job
Location
Status
Match
Docs
Updated
Actions
```

For Applications:

```text
Job
Score
Status
Docs
Updated
Actions
```

For Documents:

```text
Type
Job
Application
File
Actions
```

Actions must always remain visible.

---

# 11. DARK MODE

The project already contains theme support:

```jsx
const { theme, toggle } = useTheme();
```

and:

```jsx
<ThemeToggle theme={theme} onToggle={toggle} />
```

Do not replace the theme architecture.

Ensure delete buttons work in BOTH:

```text
light
dark
```

states.

Use semantic classes:

```css
.danger-btn {
  ...
}

.danger-btn:hover {
  ...
}

.danger-btn:disabled {
  ...
}
```

Do not hard-code a white background that becomes unreadable in dark mode.

Use existing CSS variables such as:

```css
var(--panel)
var(--border)
```

and inspect the existing color system before adding variables.

---

# 12. API DESIGN CONSISTENCY

The API composition root currently registers routers:

```python
for _router in (
    status,
    jobs,
    applications_core,
    applications_actions,
    applications_documents,
    documents,
    events,
    pipeline,
    confirmations,
):
    app.include_router(_router.router)
```

Do not move business logic into `main.py`.

The API currently uses router-level API-key authentication.

Preserve:

```python
dependencies=[Depends(require_api_key)]
```

on protected routers.

Do not create an unprotected DELETE endpoint.

---

# 13. HTTP METHODS

Use proper REST semantics:

```text
GET     read
POST    create / command
PATCH   partial update / action
DELETE  delete resource
```

Do NOT implement deletion as:

```text
POST /jobs/{id}/delete
POST /applications/{id}/remove
POST /documents/{id}/delete
```

unless an existing architectural constraint absolutely requires it.

Preferred:

```http
DELETE /api/v1/jobs/{id}
DELETE /api/v1/applications/{id}
DELETE /api/v1/documents/{id}
```

---

# 14. ERROR CONTRACT

Use existing project's error handling.

Do not return arbitrary shapes from different DELETE endpoints.

Preferred:

```text
404 → resource does not exist
409 → resource cannot be deleted because of a business constraint
422 → invalid identifier/input
500/502 → infrastructure failure
204 → successful deletion
```

If the project convention uses JSON success responses, use one consistent JSON response instead.

Do not introduce inconsistent response semantics.

---

# 15. DATABASE TRANSACTION SAFETY

For every deletion:

```python
async with session.begin():
    ...
```

or the repository's existing transaction convention.

Do not call:

```python
await session.commit()
```

in five different helper functions.

The delete operation should have one clear transaction boundary.

Example conceptual implementation:

```python
@router.delete("/{job_id}")
async def delete_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    job = await session.get(Job, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    # Determine dependent records from actual model relationships.
    # Determine MinIO artifacts.
    # Perform safe deletion.

    await session.delete(job)
    await session.commit()

    return {
        "id": str(job_id),
        "deleted": True,
    }
```

This is only a structural example.

Do NOT copy blindly.

Adapt to the project's real SQLAlchemy model and transaction pattern.

---

# 16. MINIO CLEANUP

Before implementing Document or Job deletion, inspect all code referencing:

```text
minio_key
minio_bucket
download_bytes
upload
delete
artifact_relative_path
```

If MinIO has no safe delete helper, implement one in the existing MinIO abstraction rather than calling the MinIO SDK directly from random routers.

Preferred architecture:

```text
router
  ↓
document/application service
  ↓
storage abstraction
  ↓
MinIO
```

NOT:

```text
router
  ↓
raw MinIO SDK
```

This keeps infrastructure concerns separated.

---

# 17. IDEMPOTENCY / DELETE

Deletes are destructive.

Do not blindly retry DELETE operations in a way that could hide state inconsistencies.

A second DELETE should normally return:

```text
404 Not Found
```

or a documented idempotent success.

Choose based on project convention.

Do not make a failed MinIO cleanup look like a successful deletion.

---

# 18. AUDIT / EVENTS

Inspect:

```text
pipeline_events
automation_runs
dead_letter_events
```

before deleting application/job records.

The architecture explicitly relies on events and asynchronous processing.

Do NOT leave Redis workers processing a deleted application.

Before deletion of an application that is:

```text
RUNNING
FILLING
SUBMITTING
```

inspect the orchestrator/browser-agent behavior.

You must prevent a worker from continuing to mutate an entity after it has been deleted.

Possible safe strategy:

```text
if application is RUNNING/FILLING/SUBMITTING:
    reject deletion with 409
```

OR implement a cancellation mechanism if one already exists.

Do NOT invent a cancellation architecture unless necessary.

For:

```text
CREATED
FAILED
BLOCKED
REQUIRES_HUMAN
SUBMITTED
```

deletion may be allowed if the project's business rules permit it.

Again: derive the rule from the existing state machine.

---

# 19. SECURITY

Preserve all existing security rules.

Never log:

```text
CV content
application answers
API keys
browser cookies
session tokens
MinIO secrets
```

The repository explicitly treats:

```text
job descriptions
application pages
web pages
uploaded documents
```

as untrusted input.

Do not weaken this.

Deletion endpoints must use the same API-key protection as the existing CRUD endpoints.

---

# 20. TESTS — MANDATORY

Do not consider this task complete without tests.

Add backend tests:

```text
test_delete_job_success
test_delete_job_not_found
test_delete_application_success
test_delete_application_not_found
test_delete_document_success
test_delete_document_not_found
test_delete_document_removes_storage_artifact
test_delete_job_does_not_delete_unrelated_job
test_delete_application_does_not_delete_job
```

Also test relationship behavior:

```text
job → applications
job → documents
application → questions
application → answers
application → automation runs
```

Add frontend tests if the existing frontend test setup supports them.

At minimum test:

```text
Delete button is rendered
Delete confirmation appears
Cancel does not delete
Confirm calls DELETE
Successful delete refreshes data
Failed delete shows error
Double click does not trigger two DELETE requests
```

---

# 21. API SMOKE TEST

Extend the existing API smoke test if appropriate.

The project already has:

```text
tests/integration/test_api_smoke.py
```

Use the existing conventions.

Example:

```python
response = client.delete(
    f"/api/v1/documents/{document_id}",
    headers={"X-API-Key": api_key},
)

assert response.status_code in {200, 204}
```

Do not hard-code this exact status unless it matches your chosen API contract.

---

# 22. FRONTEND API HELPER

Use the existing:

```jsx
import { fetchJson } from "../../lib";
```

and:

```jsx
await fetchJson(`/api/v1/.../${id}`, {
  method: "DELETE",
});
```

Do NOT introduce axios if the frontend does not already use it.

Do NOT introduce React Query just for this feature.

Do NOT add Redux.

Keep the architecture simple.

---

# 23. REUSABLE DELETE HANDLER

If three components need almost identical deletion logic, consider a small reusable helper.

For example:

```jsx
export async function deleteResource(path) {
  return fetchJson(path, {
    method: "DELETE",
  });
}
```

But don't create abstractions for three lines of code unless they materially improve consistency.

The goal is:

```text
simple
predictable
maintainable
```

not abstraction for abstraction's sake.

---

# 24. I18N

Add strings to BOTH:

```text
services/frontend/i18n/en.json
services/frontend/i18n/tr.json
```

Required concepts:

```text
Delete
Deleting...
Cancel
Actions
Confirm deletion
Delete job
Delete application
Delete document
Deletion failed
Deletion successful
Cannot delete running application
```

Use:

```jsx
STRINGS.deleteBtn
STRINGS.deleting
STRINGS.confirmDeleteJob
...
```

Never:

```jsx
<button>Delete</button>
```

inside the component.

---

# 25. ACCESSIBILITY

Delete buttons must have:

```jsx
type="button"
```

and meaningful accessible names.

If icon-only:

```jsx
aria-label={STRINGS.deleteBtn}
title={STRINGS.deleteBtn}
```

Prefer text + icon rather than icon-only.

Example:

```jsx
<button
  type="button"
  className="danger-btn"
  aria-label={`${STRINGS.deleteBtn}: ${j.company} — ${j.title}`}
>
  {STRINGS.deleteBtn}
</button>
```

Do not rely only on color to communicate danger.

---

# 26. DO NOT BREAK APPLICATION ACTIONS

This is critical.

Existing application actions:

```text
Prepare
Submit
View progress
Continue manually
Retry
View details
```

must continue to work exactly as before.

Delete is an additional destructive action.

Do not replace the action system with a generic CRUD table.

Example target:

```jsx
<td className="application-actions actions-sticky">

  {/* existing state-specific actions */}

  ...

  {/* destructive action always separate */}
  <button
    type="button"
    className="danger-btn"
    onClick={() => onDelete(a)}
    disabled={busyId === a.id}
  >
    {STRINGS.deleteBtn}
  </button>

</td>
```

---

# 27. JOB DELETE AND DISCOVERY

Inspect how discovered jobs are identified:

```text
jobs(source, source_job_id)
job_fingerprint
```

The data model explicitly defines uniqueness around:

```text
jobs(source, source_job_id)
```

and application fingerprinting.

Deleting a job must NOT modify the source adapter or fingerprinting logic.

After deletion, normal discovery may rediscover the same job.

That is acceptable unless the project already has a dismissed/ignored concept.

Do not change discovery semantics as part of this task.

---

# 28. DOCUMENT DELETE AND APPLICATION LINKS

Documents may have:

```text
job_id
application_id
type
language
version
minio_key
minio_bucket
metadata_json
```

When deleting:

```text
Document
```

ensure that application references do not become broken.

If another entity points to the document, inspect the FK.

Do not blindly set:

```python
application.document_id = None
```

unless the schema actually contains such a relationship.

---

# 29. ARCHITECTURAL CLEANUP TO PERFORM WHILE YOU ARE THERE

While auditing the project, identify these smells:

### A. Business logic in routers

If routers contain too much business logic:

```text
query
validation
business rules
storage
event publishing
```

do not perform a huge rewrite now.

Only extract logic if required by the deletion implementation.

Prefer:

```text
router
  ↓
service
  ↓
repository / DB
  ↓
storage/event infrastructure
```

### B. Duplicate frontend fetch logic

Do not create additional fetch patterns.

Use:

```text
fetchJson
usePolling
existing refresh functions
```

### C. Hard-coded strings

Follow existing i18n architecture.

### D. CSS duplication

Reuse:

```text
actions-sticky
refresh-btn
panel
toolbar
modal
```

where appropriate.

Add only missing semantic styles.

---

# 30. DEVOPS VALIDATION

After implementation run:

```bash
docker compose config
```

Then:

```bash
make test
```

or the repository's documented equivalent.

Also run:

```bash
pytest
```

if appropriate.

Frontend:

```bash
cd services/frontend
npm run build
```

Backend:

```bash
mypy shared/
```

if configured.

Also run lint/format according to:

```text
pyproject.toml
Makefile
.pre-commit-config.yaml
```

Do not invent new tooling.

---

# 31. DATABASE MIGRATIONS

If deletion can be implemented without schema modification:

DO NOT create a migration.

If FK/cascade behavior genuinely requires schema modification:

create a proper Alembic migration.

Never manually modify production DB schema.

Migration must be:

```text
forward
reversible where practical
tested
documented
```

---

# 32. IMPORTANT: DO NOT OVERENGINEER

This is a single-user local-first career application.

Do NOT introduce:

```text
Kafka
RabbitMQ
Kubernetes
Redis-based CRUD state
GraphQL
Redux
React Query
micro-frontends
event sourcing
CQRS
new database
new ORM
```

unless the repository already requires it.

Existing architecture already has:

```text
PostgreSQL
Redis Streams
MinIO
Docker Compose
FastAPI
Next.js
```

Use those.

---

# 33. ACCEPTANCE CRITERIA

The task is COMPLETE only if ALL are true:

## Jobs

* [ ] Actions column exists.
* [ ] Delete button exists.
* [ ] Delete confirmation exists.
* [ ] DELETE API exists.
* [ ] API key required.
* [ ] 404 handled.
* [ ] Related records handled correctly.
* [ ] MinIO artifacts handled correctly.
* [ ] UI refreshes after delete.
* [ ] Error shown if deletion fails.

## Applications

* [ ] Delete button exists.
* [ ] Existing Prepare/Submit/View/Continue/Retry/Details actions still work.
* [ ] DELETE API exists.
* [ ] Related questions/answers/runs handled correctly.
* [ ] Running application cannot be silently deleted.
* [ ] UI refreshes correctly.

## Documents

* [ ] Delete button exists.
* [ ] DELETE API exists.
* [ ] MinIO object cleanup handled.
* [ ] Versioning semantics preserved.
* [ ] Application links remain consistent.
* [ ] UI refreshes correctly.

## UI

* [ ] Works in light mode.
* [ ] Works in dark mode.
* [ ] No horizontal scrolling caused by action columns.
* [ ] Action columns remain visible.
* [ ] Long text truncates.
* [ ] Buttons do not overflow table.
* [ ] Responsive behavior preserved.
* [ ] Turkish translations added.
* [ ] English translations added.
* [ ] Accessible buttons.

## Backend

* [ ] RESTful DELETE.
* [ ] Transaction safe.
* [ ] API-key protected.
* [ ] No secret leakage.
* [ ] No orphaned DB records.
* [ ] No orphaned MinIO artifacts.
* [ ] No invalid worker state.

## Tests

* [ ] Backend delete tests.
* [ ] Not-found tests.
* [ ] Relationship tests.
* [ ] MinIO cleanup tests.
* [ ] Frontend delete behavior tested if frontend test framework exists.
* [ ] Full existing test suite passes.
* [ ] Frontend build passes.
* [ ] Docker Compose validation passes.

---

# 34. FINAL CODE REVIEW

After implementation, do NOT immediately say "done".

Perform a second independent review.

Pretend you are reviewing another senior engineer's PR.

Check:

```text
Architecture
API
Database
Transactions
MinIO
Redis/events
Concurrency
Frontend
Responsive UI
Dark mode
i18n
Accessibility
Security
Tests
Docker
CI
```

Specifically search for:

```text
TODO
FIXME
pass
except Exception
console.log
print(
hard-coded "Delete"
hard-coded "Deleting"
duplicate DELETE
unused imports
unused props
unused state
dead CSS
incorrect colSpan
incorrect table widths
```

Fix issues you find.

---

# 35. DO NOT STOP AFTER FIRST ERROR

If tests fail:

1. Determine root cause.
2. Fix the root cause.
3. Re-run the relevant test.
4. Re-run the full suite.
5. Do not simply weaken/delete the failing test.

Never do:

```python
@pytest.mark.skip
```

just to make CI green.

Never remove assertions to hide a bug.

---

# 36. REQUIRED FINAL RESPONSE FROM THE CODING AGENT

At the end report:

```text
IMPLEMENTED
----------

Backend:
- ...
- ...

Frontend:
- ...
- ...

Database:
- ...

MinIO:
- ...

Tests:
- ...

Validation:
- ...

Files changed:
- ...

Commit:
<commit hash>

Potential remaining risks:
- ...
```

Keep this factual.

Do not claim something was tested if it was not actually tested.

---

# 37. COMMIT

When everything passes, create ONE focused commit:

```text
feat: add safe delete actions for jobs applications and documents
```

Do not mix unrelated refactoring into the commit.

If unrelated serious bugs are discovered, list them separately instead of silently expanding scope.

---

# FINAL PRINCIPLE

The goal is NOT merely:

"put three red Delete buttons into the UI."

The goal is:

```text
USER
 ↓
DELETE BUTTON
 ↓
CONFIRMATION
 ↓
REST DELETE
 ↓
API AUTH
 ↓
BUSINESS VALIDATION
 ↓
TRANSACTION
 ↓
POSTGRES
 ↓
MINIO CLEANUP
 ↓
EVENT/WORKER SAFETY
 ↓
CONSISTENT RESPONSE
 ↓
FRONTEND REFRESH
 ↓
USER SEES CORRECT STATE
```

Implement the complete lifecycle.

Do not sacrifice data integrity for UI convenience.

Do not sacrifice the existing application automation state machine for CRUD simplicity.

Do not redesign the whole project.

Make the smallest clean architectural change that produces production-quality behavior.
