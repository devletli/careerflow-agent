# AI Job Agent — Microservice Edition

A modular AI job-search and application pipeline.

## Architecture

Services:
- `orchestrator`: schedules and coordinates the pipeline
- `job-discovery`: discovers public jobs (initially Workable)
- `job-matching`: computes explainable 0–100 match scores
- `cv-generator`: creates job-specific CVs
- `application-analyzer`: analyzes application forms/questions
- `browser-agent`: flexible Playwright automation for multiple ATS/application sites
- `api`: shared REST API for dashboard/control
- `postgres`: persistent authoritative state (12 core tables, Alembic migrations)
- `redis`: queue/event transport (Redis Streams, consumer groups, dead-letter routing)
- `minio`: document/artifact storage (private bucket enforcement)
- `frontend`: dashboard

The system is deliberately asynchronous and idempotent. Every stage reads/writes database state and can be rerun safely.

## Phase Status

- [x] **Phase 0 — Infrastructure & Foundations**: Docker Compose, PostgreSQL schema & Alembic migrations, Redis Streams bus, MinIO client, Shared contracts & fingerprinting, Orchestrator state machine & duplicate detection, API health endpoints, and full test suite.
- [x] **Phase 1 — Canonical Profile & Preferences**: `profile/profile.yaml` + `profile/preferences.yaml` loader, master CV parsing (`shared/profile/loader.py`).
- [x] **Phase 2 — Job Discovery**: `JobSourceAdapter` interface with live connectors for Workable, Greenhouse, Lever, Ashby, and SmartRecruiters public job boards, deduplication by `(source, source_job_id)` and job fingerprint, incremental discovery loop.
- [x] **Phase 3 — Matching Engine**: deterministic requirement extraction + semantic scoring + LLM explanation, configurable weighted score and threshold (`MIN_MATCH_SCORE`).
- [x] **Phase 4 — Document Generation**: job-specific CV/cover-letter generation, language detection, MinIO artifact storage.
- [x] **Phase 5 — Form Analysis**: application form/question inspection and classification (legal/work-authorization, preference, open-ended).
- [x] **Phase 6 — Generic Browser Automation**: Playwright-based `browser-agent` with accessible-locator-first form filling, CAPTCHA/login-wall/MFA detection with hard stop, file upload support. *(Still a single worker module rather than fully split `BrowserAutomationEngine` + per-site `SiteAdapter` classes — see Remaining Risks.)*
- [x] **Phase 7 — Pipeline Automation & Rate Limiting**: event-driven orchestrator with bounded exponential backoff, dead-letter routing, duplicate/eligibility checks, and daily/hourly rate limits before any submission.
- [x] **Phase 8 — Frontend Dashboard**: Next.js dashboard (Overview, Jobs, Applications, Events, Settings) served at `http://localhost:3000`, proxied to the API through Next.js rewrites.
- [ ] **Phase 9 — Additional ATS Connectors**: Greenhouse/Lever/Ashby/SmartRecruiters discovery connectors exist; a dedicated `generic` fallback adapter is present but application-side (submission) adapters remain Workable/BrowserAgent-generic only.
- [ ] **Phase 10 — Hardening & Load Testing**: load tests, browser regression fixtures, and backup/restore runbooks are not yet implemented.

## Quick Start

1. Copy `.env.example` to `.env`.
2. Put your master CV at `profile/master_cv.pdf`.
3. Edit `profile/profile.yaml` and `profile/preferences.yaml`.
4. Run:

```bash
docker compose up --build
```

5. API: `http://localhost:8000` (`/health`, `/api/v1/status`, `/api/v1/jobs`, `/api/v1/applications`, `/api/v1/events`)
6. Frontend dashboard: `http://localhost:3000` (Overview / Jobs / Applications / Events / Settings tabs, auto-refreshing every 10s). The Overview tab provides confirmed actions for discovery, matching, document generation, form analysis, and form filling.
7. MinIO Console: `http://localhost:9001` (Credentials: minioadmin / minioadmin)

> **Note:** MinIO removed the `minio/minio` image from Docker Hub, so `docker-compose.yml` pins `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` instead.

## Running Tests

Run the complete unit and integration test suite (pure-Python, no Docker services required — DB/Redis/MinIO calls are mocked or use in-memory SQLite):

```bash
python -m venv .venv
.venv\Scripts\pip install -e ./shared pytest pytest-asyncio aiosqlite
.venv\Scripts\python -m pytest -v
```

Validate Docker Compose configuration:

```bash
docker compose config
```

Run database migrations manually (already run automatically by the `init-db` one-shot service):

```bash
alembic -c db/alembic.ini upgrade head
```

## Design Principles

- One source of truth for the candidate profile.
- Database is the authoritative pipeline state.
- Object storage is the document/artifact store.
- Redis carries jobs/events via versioned contracts.
- Every stage is idempotent with database constraints and state checks.
- Every job and application has a deterministic SHA-256 fingerprint.
- LLMs never invent candidate facts.
- Site-specific browser logic is implemented through adapters, not hard-coded into the core agent.
- `AUTOMATION_MODE=PREPARE_APPLICATION` (the default) fills but never submits. The dashboard's per-application **Playwright ile Gönder** control requires an explicit confirmation and submits only that selected application in the same browser session used to fill it. `AUTO_SUBMIT=true` + `FULL_AUTO` remain required for unattended submission.
- **Tarayıcıda Aç** opens the selected application URL in the user's regular browser so the user can complete a CAPTCHA, sign-in, MFA, or a question that cannot be answered from verified profile facts. The agent never bypasses these checks.

### Visible local Playwright helper (Windows)

The Docker browser worker must remain headless, so use the desktop helper when you want Playwright to fill safe fields in a visible browser that remains open for you:

```powershell
.\scripts\install-desktop-runner.ps1
```

After installation, use **Playwright ile Doldur** in the dashboard's **Applications** tab. It starts a local Chromium session, fills only verified profile answers and available documents, then leaves the browser open. Complete CAPTCHA, sign-in/MFA, and any unanswered questions yourself, then review and submit in that same visible browser window.

## Gemini Configuration

Gemini is the default LLM provider. Add a Gemini API key to `.env` before starting the stack:

```dotenv
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash
GEMINI_API_KEY=your_api_key
```

The application uses Google’s official `google-genai` SDK and asks Gemini for JSON-only structured responses. If no key is configured, matching retains its deterministic behavior and uses the existing safe fallback rather than inventing candidate information.

The numeric match score and qualification are always deterministic and based only on verified profile facts. Gemini supplies a concise narrative/risk explanation only for `REVIEW` and `QUALIFIED` results; it cannot change the score or make an ineligible job eligible. This keeps the free-tier Gemini request rate within its limits and guarantees that matching continues when the provider is unavailable.

## Remaining Risks / Known Limitations

- The browser-agent's Playwright logic lives in one `worker.py` module; splitting it into a formal `BrowserAutomationEngine` core plus per-site `SiteAdapter` classes (as described in the master build prompt) would improve testability and make adding new ATS targets safer.
- No local mock/fixture HTML application forms exist yet for repeatable browser regression tests; current browser-agent runs exercise real public job boards in `PREPARE_APPLICATION` mode (fill-only, never submits).
- `BROWSER_HEADLESS` must stay `true` in Docker (no X server in the containers); this is now the default in `.env`/`.env.example`.
- Additional ATS *submission* adapters (Greenhouse/Lever/Ashby/SmartRecruiters-specific form flows) are not yet implemented; only discovery-side connectors exist for those sources.
