You are working inside the existing LOCAL repository:

careerflow-agent

This is a STABILIZATION PATCH.

The previous work added evaluation tests, browser regression tests, CI and English UI.

Now the priority is different:

> Verify that the application actually works end-to-end locally, identify UI elements that are hidden/cut off/broken, identify service integration problems, and fix them with the smallest possible changes.

The user will review and commit the changes manually.

## ABSOLUTE GIT RULE

DO NOT:

* git commit
* git push
* amend commits
* reset
* rebase
* rewrite history
* create branches

Only use read-only git commands such as:

git status
git diff
git diff --stat
git log

All modifications must remain UNCOMMITTED in the local working tree.

---

# PHASE 1 — UNDERSTAND THE CURRENT STATE

Before changing anything, inspect:

* repository structure
* README
* docker-compose files
* Dockerfiles
* backend services
* frontend
* API routes
* frontend API clients
* environment configuration
* service-to-service URLs
* health checks
* existing tests
* previous evaluation tests
* browser regression tests
* CI workflow

Also inspect the current git status.

Do NOT immediately start editing.

First build a mental map of:

Frontend
↓
API / Gateway
↓
Backend services
↓
Database / external dependencies

Identify every service defined by Docker Compose and what depends on what.

---

# PHASE 2 — ACTUALLY RUN THE APPLICATION

Do not rely only on source-code inspection.

Start the application using the repository's documented local development procedure.

Use the existing commands from README/package files/docker-compose.

If Docker Compose is the intended development environment, use it.

Verify:

* containers start
* containers remain running
* health checks work
* frontend is reachable
* backend/API is reachable
* services can communicate
* database connection works if applicable

Inspect logs for:

* connection refused
* wrong hostname
* wrong port
* missing environment variable
* CORS
* 404
* 401/403
* 500
* timeout
* startup race conditions
* frontend API URL errors

Do not hide errors just to make the application appear healthy.

---

# PHASE 3 — FRONTEND VISUAL / LAYOUT AUDIT

This is a HIGH PRIORITY task.

Use the existing browser tooling if available.

Open the actual frontend locally.

Inspect the main screens at:

1. desktop ~1440x900
2. laptop ~1280x800
3. smaller desktop ~1024x768
4. mobile/tablet width if the application claims responsive support

Look specifically for:

* buttons not visible
* buttons clipped
* buttons outside viewport
* text overflowing
* cards wider than viewport
* horizontal scrolling
* sidebar covering content
* header covering content
* fixed elements overlapping content
* modals extending outside viewport
* tables wider than screen
* action buttons hidden below fold
* navigation items disappearing
* icons without usable labels
* insufficient spacing
* unreadable text
* disabled buttons that look active
* loading states that never finish
* empty states
* error states
* inconsistent English labels

Do NOT redesign the UI.

Fix only actual usability/layout problems.

---

# PHASE 4 — CHECK EVERY IMPORTANT BUTTON

Create a practical UI checklist from the existing application.

For each important visible action, verify:

Button/action
↓
frontend handler
↓
API request
↓
backend route
↓
service
↓
response
↓
frontend state update

Pay particular attention to:

* Search Jobs
* Run Matching
* Generate CV
* Analyze Job
* Open Job
* Application
* Browser automation
* Profile
* Settings
* Refresh
* Retry
* navigation items

Do not assume that because a button renders, it works.

For every broken action:

1. Find the root cause.
2. Fix the smallest possible layer.
3. Retest.

---

# PHASE 5 — SERVICE INTEGRATION AUDIT

Check service communication carefully.

For each service determine:

* port
* hostname
* health endpoint
* dependencies
* environment variables
* internal URL
* frontend/public URL where applicable

Look for common Docker mistakes:

BAD:

http://localhost:8000

when one container needs to call another container.

Use the appropriate Docker service hostname instead.

Also check:

* port collisions
* startup ordering
* health checks
* incorrect container names
* incorrect API prefixes
* CORS configuration
* frontend environment variables
* backend environment variables
* database connection strings
* missing dependencies
* stale environment variable names

Do not change architecture.

Only fix incorrect configuration or broken integration.

---

# PHASE 6 — API CONTRACT CHECK

Compare:

frontend API calls

against:

actual backend routes.

Look for:

* wrong paths
* wrong HTTP methods
* wrong request body
* wrong field names
* wrong response fields
* incorrect status handling
* incorrect error handling
* stale API endpoints
* frontend expecting fields that backend no longer returns

If a frontend call is broken, fix the smallest side necessary.

Do not introduce a new API abstraction unless the existing code genuinely requires it.

---

# PHASE 7 — LOADING / ERROR STATES

Inspect every major async operation.

A user should never see:

* permanently spinning loader
* blank screen
* invisible error
* button doing nothing
* duplicate requests caused by repeated clicks

Where appropriate add:

* loading state
* disabled state during request
* visible error message
* retry action
* empty state

Keep implementation simple.

---

# PHASE 8 — RESPONSIVE LAYOUT FIXES

If elements do not fit the viewport, fix the actual CSS/layout issue.

Prefer existing layout system/components.

Typical acceptable fixes:

* flex-wrap
* grid minmax()
* overflow-x:auto where appropriate
* max-width
* min-width:0
* responsive breakpoints
* button wrapping
* responsive padding
* sidebar collapse
* table horizontal scrolling

Avoid arbitrary pixel hacks.

Do not redesign the entire component hierarchy.

---

# PHASE 9 — REGRESSION TESTS

For every bug you fix that can reasonably be tested:

add or update a regression test.

Prioritize:

* previously invisible buttons
* broken API calls
* broken service URLs
* frontend/backend contract mismatches
* browser automation flow
* critical navigation

Use the existing testing infrastructure.

Do not create a huge E2E framework.

---

# PHASE 10 — FULL LOCAL VALIDATION

After fixes, run:

1. backend tests
2. matching evaluation
3. browser regression tests
4. frontend lint
5. frontend build
6. relevant integration tests
7. Docker Compose validation
8. local application smoke test

Then actually open the frontend again.

Verify visually that:

* buttons fit
* content is not clipped
* navigation works
* main actions are visible
* API-backed pages load
* errors are visible when appropriate
* no obvious console errors remain

If browser automation is available, check browser console errors and failed network requests.

---

# IMPORTANT SCOPE CONTROL

Do NOT:

* redesign the application
* replace the frontend framework
* replace the backend framework
* rewrite services
* merge services
* split services
* add Kubernetes
* add Redis just because it might help
* add Kafka
* add another database
* add another LLM
* add RAG
* add observability stack
* add authentication unless something is actually broken because of it
* add unnecessary dependencies

This is a PATCH, not a rewrite.

---

# PRIORITY ORDER

If you discover many problems, fix them in this order:

P0 — Application cannot start
P1 — Frontend cannot communicate with backend
P2 — Main functionality is broken
P3 — Important buttons/actions invisible or unusable
P4 — Layout/responsive problems
P5 — Loading/error-state problems
P6 — Minor visual polish

Do not spend time on P6 while P0–P3 remain.

---

# IF SOMETHING IS ALREADY WORKING

Leave it alone.

Do not refactor code simply because you dislike its style.

The objective is stability, not code beautification.

---

# FINAL REVIEW

Before finishing:

git status
git diff --stat
git diff

Check for:

* accidental secrets
* .env files
* generated files
* node_modules
* build artifacts
* temporary screenshots
* debug code
* console.log statements added only for debugging
* accidental dependency changes

Remove temporary debugging code.

---

# FINAL REPORT

Report:

## 1. Problems found

Group them:

* UI
* frontend/API
* services/Docker
* browser automation
* tests

## 2. Problems fixed

List exact fixes.

## 3. Tests executed

Show exact commands and results.

## 4. Remaining problems

Only genuine unresolved problems.

## 5. Files changed

List important files.

## 6. Git

Confirm:

No commit was created.
No push was performed.
All changes remain local and uncommitted.

IMPORTANT:

Do not stop at static code analysis.

Actually run the application and inspect the frontend.

The user's main concern is that some buttons do not fit/appear and that some services may not work correctly.

Find the actual causes and fix them.
