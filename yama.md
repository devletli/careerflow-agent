You are working inside the EXISTING LOCAL repository:

careerflow-agent

This is NOT a greenfield implementation.

The application already contains:

* Next.js frontend
* API service
* job discovery
* deterministic job matching
* LLM-assisted explanations
* CV/document generation
* application analysis
* Playwright browser automation
* PostgreSQL
* Redis
* MinIO
* orchestrator/pipeline
* Docker Compose

The previous changes introduced evaluation/testing/CI work and English UI.

The current application now has quality problems.

The user specifically reports:

1. The Applications tab has become visually smaller / worse.
2. Some buttons/actions are not visible or do not fit.
3. The Documents tab displays `Artifact Path` as plain text instead of a useful clickable document link.
4. Generated documents are extremely basic and visually poor.
5. There may be service/API integration problems.
6. The UI needs a complete practical review rather than another isolated CSS fix.

Your task is to perform a REAL LOCAL CODE REVIEW first, then implement a focused stabilization/product-quality patch.

---

# ABSOLUTE GIT RULE

The user will commit manually.

DO NOT:

* git commit
* git push
* amend commits
* reset
* rebase
* rewrite history
* create branches

You may use:

git status
git log
git diff
git diff --stat

All changes must remain uncommitted in the local working tree.

---

# PART 1 — FULL REPOSITORY DISCOVERY

Before modifying anything, inspect the repository thoroughly.

Do NOT guess filenames.

First discover the actual structure.

Inspect:

* frontend/
* services/
* shared/
* db/
* tests/
* scripts/
* docker-compose.yml
* README.md
* architecture.md
* data-model.md
* implementation-plan.md
* SPEC.md

Also inspect package/dependency files:

* package.json
* pyproject.toml
* requirements files
* Dockerfiles
* tsconfig
* Next.js configuration
* Tailwind/config files if present

Find the ACTUAL files implementing:

## Frontend

* application dashboard
* Applications tab/page
* Documents tab/page
* document/artifact list
* job cards
* application cards
* navigation/sidebar
* header
* buttons/actions
* modals/dialogs
* responsive layout
* API client/hooks

## Backend

Find actual implementations for:

* applications API
* documents/artifacts API
* MinIO storage
* document generation
* CV generation
* cover-letter generation
* application analysis
* browser automation
* service-to-service communication

Do not invent paths.

At the beginning of the work, produce an internal map like:

Frontend: <actual file paths>

Applications: <actual file paths>

Documents: <actual file paths>

Document generation: <actual file paths>

Artifact storage: <actual file paths>

API: <actual file paths>

Do not create a new architecture document just for this task unless absolutely necessary.

---

# PART 2 — RUN THE CURRENT APPLICATION BEFORE CHANGING IT

This is mandatory.

Use the repository's documented startup process.

Prefer:

docker compose up --build

if that is the intended development workflow.

Check:

* all containers start
* no restart loops
* API responds
* frontend responds
* PostgreSQL works
* Redis works
* MinIO works
* service-to-service communication works

Inspect logs.

Look for:

* connection refused
* incorrect Docker hostname
* incorrect ports
* 404
* 401
* 403
* 422
* 500
* timeout
* CORS
* missing environment variables
* startup race conditions
* failed migrations
* MinIO errors
* Redis errors

Do not fix UI problems while ignoring broken backend services.

---

# PART 3 — REAL FRONTEND AUDIT

Open the actual frontend in a browser.

Do not rely only on source-code inspection.

Test at least:

1440x900
1280x800
1024x768

If practical also check:

390x844

The application is a portfolio project.

The UI must look like a real usable professional dashboard.

Audit:

* Overview
* Jobs
* Applications
* Documents
* Events
* Settings

If a Documents tab does not exist as a dedicated route/tab, locate where generated artifacts are displayed.

---

# PART 4 — APPLICATIONS TAB

This is HIGH PRIORITY.

The user reports that the Applications tab became smaller/worse after previous changes.

Find the ROOT CAUSE.

Inspect:

* page/container width
* sidebar width
* main content width
* card width
* table width
* grid columns
* flex layout
* max-width
* min-width
* padding
* responsive breakpoints
* action button layout

Do not simply increase the entire application width blindly.

The intended desktop layout should use the available viewport effectively.

A reasonable target is:

Sidebar:
fixed but compact

Main:
flex: 1
min-width: 0
width: 100%

Content:
max-width only where it improves readability

Application list:
use available horizontal space

Application card/table:
actions remain visible

If the application list is card-based, cards should not become unnecessarily narrow.

If table-based, use horizontal scrolling only when truly necessary.

Action buttons must remain visible.

If there are several actions, use:

display:flex;
flex-wrap:wrap;
gap:...

instead of fixed widths that cause clipping.

DO NOT introduce arbitrary large fixed widths.

---

# PART 5 — APPLICATION ACTIONS

Inspect every application action.

Examples may include:

* Open Job
* View Details
* Generate CV
* Generate Cover Letter
* Analyze
* Browser Fill
* Open in Browser
* Submit
* Retry
* Refresh
* Delete

Use the ACTUAL actions found in the code.

For every action verify:

UI button
→ frontend handler
→ API call
→ backend route
→ service
→ database/storage
→ response
→ UI state update

If a button exists but does nothing:

find the actual cause.

Do not hide the button.

Do not remove functionality merely because it is currently broken.

---

# PART 6 — DOCUMENTS / ARTIFACT PATH

This is explicitly required.

Find the actual frontend component that displays:

`Artifact Path`

and find the backend/API response that provides that value.

Currently it appears to expose a filesystem/object-storage path as plain text.

That is NOT acceptable as the primary user experience.

Determine how artifacts are stored.

The repository documentation states that MinIO is the document/artifact store.

Inspect the existing artifact storage implementation.

DO NOT expose:

* MinIO internal filesystem paths
* server filesystem paths
* private bucket paths
* credentials
* internal Docker paths

Instead implement a proper user-facing document access mechanism.

Preferred architecture:

Frontend:
Artifact name / document type
+
"Open"
+
"Download"

Backend:
provide a safe artifact access endpoint or presigned URL mechanism using the existing MinIO integration.

The endpoint must:

1. verify the artifact exists
2. prevent arbitrary object access
3. use the existing application/storage ownership model
4. return a browser-accessible response or safe temporary URL
5. preserve the original filename/content type where possible

If the existing API already has a secure artifact endpoint, USE IT.

Do not create a duplicate storage system.

For the frontend, replace raw:

Artifact Path:
/some/internal/path/...

with something like:

Document
resume.pdf

[Open] [Download]

or:

CV — Senior DevOps Engineer
[View] [Download]

The raw internal artifact path should not be the main displayed value.

You may retain it only as developer/debug metadata if genuinely useful.

---

# PART 7 — DOCUMENT GENERATION QUALITY

This is another HIGH PRIORITY problem.

Inspect the complete document-generation pipeline.

Trace:

job
→ candidate profile
→ matching
→ prompt
→ generated content
→ document renderer
→ artifact storage
→ frontend display

Identify exactly what currently generates:

* CV
* cover letter
* other documents

Determine whether the output is:

* plain text
* markdown
* HTML
* DOCX
* PDF
* template-based
* LLM-generated
* minimally formatted

Do not replace the entire document system blindly.

The objective is to produce documents that are genuinely portfolio/demo quality.

---

# PART 8 — CV QUALITY

The generated CV must not look like raw generated text.

Inspect the existing master CV/profile structure.

Preserve factual information from the candidate profile.

The generated CV should have a professional hierarchy such as:

Header
Name
Role / professional title
Contact information

Professional Summary

Core Skills

Professional Experience

Education

Certifications

Languages

Projects / Additional Information where appropriate

The exact sections must follow the actual profile data.

Do NOT invent:

* employers
* dates
* technologies
* qualifications
* metrics
* achievements

The LLM may tailor wording to the job but must remain grounded in verified profile data.

---

# PART 9 — COVER LETTER QUALITY

Cover letters should be actual professional documents, not a few generic sentences.

Use:

* candidate profile
* target job
* company name
* job title
* relevant experience
* relevant skills

Structure approximately:

Greeting

Opening:
specific interest in role/company

Relevant experience:
2–3 concrete connections between candidate and job

Value:
why the candidate's experience is relevant

Closing:
professional call to action

Signature

Avoid:

* generic AI filler
* exaggerated claims
* fabricated achievements
* repetitive wording
* "I am excited to apply..." repeated in every document

The LLM should tailor the document to the job while remaining factual.

---

# PART 10 — DOCUMENT RENDERING

Inspect the existing renderer.

If the project already generates PDF/DOCX:

IMPROVE the existing renderer.

Do NOT introduce a second document-generation framework unless the existing implementation cannot produce usable documents.

The rendered result should have:

* consistent typography
* headings
* spacing
* readable margins
* page breaks
* bullet lists
* proper date formatting
* consistent alignment
* professional hierarchy

Avoid:

* giant empty spaces
* text touching page edges
* orphan headings
* broken bullets
* raw Markdown syntax
* raw JSON
* raw prompt output
* excessive decorative elements

If HTML → PDF is already used, improve the HTML/CSS template.

If DOCX is used, improve its existing styles.

If Markdown is used only as an intermediate representation, ensure the final artifact is properly rendered.

---

# PART 11 — DOCUMENT PREVIEW

Inspect how documents are displayed in the UI.

If the current UI only shows:

filename
artifact path
timestamp

then improve it.

The user should be able to understand:

Document type
Target job
Created date
Status
File type

and access it directly.

Prefer:

[View] [Download]

If a preview is technically easy using the existing infrastructure, provide it.

Do NOT build a complex document editor.

---

# PART 12 — API / SERVICE CONTRACT REVIEW

Trace the frontend requests for:

Applications
Documents
Jobs
Matching
Events

against the actual backend routes.

Find mismatches such as:

frontend:
GET /api/...

backend:
GET /api/v1/...

or:

frontend expects:
artifact_url

backend returns:
artifact_path

Fix the actual contract.

Do not add duplicate endpoints if an existing endpoint can be corrected.

Check:

* HTTP methods
* route prefixes
* request bodies
* response schemas
* field names
* error handling
* status codes

---

# PART 13 — SERVICE HEALTH

Review Docker Compose and service dependencies.

For every service verify:

* container name
* port
* environment variables
* dependency
* health check
* internal hostname
* API endpoint

Remember:

inside Docker:

localhost != another container

Services should communicate using Docker service names.

Do not introduce a service-discovery system.

---

# PART 14 — FRONTEND STATE / LOADING / ERRORS

Inspect every major API-backed page.

Avoid:

* blank screens
* buttons doing nothing
* permanent spinners
* stale data after mutation
* duplicate requests
* silent errors

For important operations:

loading
→ request
→ success state

or:

loading
→ request
→ visible error + retry

Use the existing frontend state management.

Do not introduce Redux/Zustand/etc. unless the project already uses it and actually requires a correction.

---

# PART 15 — RESPONSIVE DESIGN

Fix the actual layout problems.

Use the project's existing CSS/Tailwind/component system.

Prefer:

flex-wrap
grid
minmax()
min-width: 0
responsive breakpoints
overflow-x:auto for tables
responsive padding

Avoid:

* giant fixed widths
* negative margins
* arbitrary transforms
* absolute positioning used to patch layout
* hiding important buttons on smaller screens

The application must remain usable at:

1440x900
1280x800
1024x768

---

# PART 16 — DESIGN CONSISTENCY

Perform a visual consistency review.

Check:

* typography
* button sizes
* border radius
* spacing
* cards
* tables
* badges
* status colors
* icons
* empty states
* loading states
* error states

Do NOT perform a full visual redesign.

Keep the existing design language.

The goal is:

clean
consistent
professional
functional

---

# PART 17 — TESTS FOR THE ACTUAL BUGS

Add regression coverage for the bugs discovered.

At minimum cover:

## Applications

* page renders
* applications use available content width
* primary actions are visible
* action buttons do not overflow

## Documents

* artifact metadata renders
* raw internal path is not the primary UI
* Open/Download action exists
* artifact access uses the safe API mechanism

## Services

* applications endpoint works
* documents/artifacts endpoint works
* health endpoint works

## Document generation

* CV generation produces non-empty meaningful content
* cover letter generation produces non-empty meaningful content
* generated artifact is stored successfully

Use existing test infrastructure.

Do not create a giant new testing framework.

---

# PART 18 — MANUAL BROWSER ACCEPTANCE TEST

After coding, actually open the application.

Test this sequence:

1. Open dashboard.
2. Open Jobs.
3. Open an existing job.
4. Trigger matching if available.
5. Generate a CV.
6. Generate a cover letter.
7. Open Applications.
8. Inspect application card/table width.
9. Click relevant application action.
10. Open Documents.
11. Confirm generated document is visible.
12. Confirm Artifact Path is no longer just raw text.
13. Click Open/View.
14. Click Download if available.
15. Verify the document is actually accessible.
16. Inspect the generated document visually.

If document generation is slow, wait for completion instead of declaring failure prematurely.

---

# PART 19 — DOCUMENT QUALITY ACCEPTANCE

Inspect an actual generated CV and cover letter.

Do not merely check HTTP 200.

The document must be:

* readable
* structured
* professional
* factually grounded
* properly formatted
* usable as an application document

If the generated document is still obviously poor, continue fixing the actual generation/template pipeline.

---

# PART 20 — DO NOT OVERENGINEER

Absolutely do NOT:

* rewrite the architecture
* merge services
* split services
* introduce Kubernetes
* introduce Kafka
* introduce another database
* introduce another LLM
* introduce RAG
* introduce another frontend framework
* build a new design system
* build a full document editor
* implement enterprise authentication
* implement production observability

This is a stabilization/product-quality patch.

---

# PART 21 — IMPLEMENTATION STYLE

IMPORTANT:

Do not make broad speculative changes.

For every bug:

1. Identify root cause.
2. Identify exact file.
3. Identify exact function/component.
4. Make the smallest correct change.
5. Test it.
6. Check for regressions.

If a component is genuinely badly structured, refactor only that component.

Do not perform unrelated cleanup.

---

# PART 22 — FINAL CODE REVIEW

Run:

git status
git diff --stat
git diff

Inspect all modifications.

Remove:

* debug logging
* temporary files
* screenshots
* generated artifacts
* secrets
* .env files
* node_modules
* build artifacts

Do not commit.

---

# FINAL REPORT

Return:

## Repository map

Actual files discovered for:

* frontend
* Applications
* Documents
* artifact storage
* document generation
* API
* browser automation

## Problems found

Group:

* UI
* Applications
* Documents
* document generation
* API
* services
* tests

## Root causes

For every important problem, state:

file
component/function
root cause

## Changes made

State:

file
change
reason

## Tests executed

Exact commands and results.

## Manual browser verification

State which viewport sizes were checked.

## Document verification

State which generated artifacts were inspected and whether they were actually accessible/rendered.

## Remaining problems

Only genuine unresolved issues.

## Git

Confirm:

No commit.
No push.
Changes remain local and uncommitted.

IMPORTANT:

Do not stop after static inspection.

Run the application.

Inspect the actual UI.

Trace the actual API calls.

Inspect actual generated documents.

Fix root causes rather than applying superficial CSS patches.
