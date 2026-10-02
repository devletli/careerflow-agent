# AI Job Agent — Microservice Edition

An AI-powered job-search/career agent providing:

- job discovery across public ATS job boards and German-market sources
- deterministic profile/job matching with LLM-assisted reasoning
- job-specific CV and cover-letter generation
- application-form analysis with safe-answer resolution
- browser-assisted application workflow with human-in-the-loop safety

The system fills forms but never submits without explicit confirmation
(`AUTOMATION_MODE=PREPARE_APPLICATION` by default, `AUTO_SUBMIT=false`).

## Quality

- Matching evaluation dataset (`evals/matching_cases.json`, 25 synthetic cases)
  with automated evaluation (`tests/evals/test_matching_eval.py`) that runs
  the production matcher offline — no LLM access required.
- Browser regression fixture (`tests/fixtures/application_form.html`) covering
  field detection, safe-answer resolution, CAPTCHA non-bypass, and a Playwright
  fill-without-submit check (`tests/unit/test_browser_regression.py`).
- Minimal GitHub Actions CI (`.github/workflows/ci.yml`): backend tests,
  Chromium browser regression, frontend production build, Compose validation.
- API smoke/performance regression test (`tests/integration/test_api_smoke.py`):
  read-only burst against the real FastAPI app with mocked dependencies.
  This is a smoke test, not production load testing.

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
- `frontend`: dashboard (English UI)

The system is deliberately asynchronous and idempotent. Every stage reads/writes database state and can be rerun safely.

The current architecture is retained for now. For a single-user deployment, future work may simplify service boundaries and reduce operational complexity.

## Phase Status

- [x] **Phase 0 — Infrastructure & Foundations**: Docker Compose, PostgreSQL schema & Alembic migrations, Redis Streams bus, MinIO client, Shared contracts & fingerprinting, Orchestrator state machine & duplicate detection, API health endpoints, and full test suite.
- [x] **Phase 1 — Canonical Profile & Preferences**: `profile/profile.yaml` + `profile/preferences.yaml` loader, master CV parsing (`shared/profile/loader.py`).
- [x] **Phase 2 — Job Discovery**: `JobSourceAdapter` interface with live connectors for Workable, Greenhouse, Lever, Ashby, and SmartRecruiters public job boards, plus German-market sources (Bundesagentur für Arbeit job search and the Arbeitnow job-board API), deduplication by `(source, source_job_id)` and job fingerprint, incremental discovery loop. The first entry of `locations` in `profile/preferences.yaml` is passed to adapters that support location filtering.
- [x] **Phase 3 — Matching Engine**: deterministic requirement extraction + semantic scoring + LLM explanation, configurable weighted score and threshold (`MIN_MATCH_SCORE`).
- [x] **Phase 4 — Document Generation**: job-specific CV/cover-letter generation, language detection, MinIO artifact storage.
- [x] **Phase 5 — Form Analysis**: application form/question inspection and classification (legal/work-authorization, preference, open-ended).
- [x] **Phase 6 — Generic Browser Automation**: Playwright-based `browser-agent` with accessible-locator-first form filling, CAPTCHA/login-wall/MFA detection with hard stop, file upload support, structured as a `BrowserAutomationEngine` core with per-site `SiteAdapter` classes (`workable`, `generic` fallback) plus a dedicated `safety` module.
- [x] **Phase 7 — Pipeline Automation & Rate Limiting**: event-driven orchestrator with bounded exponential backoff, dead-letter routing, duplicate/eligibility checks, and daily/hourly rate limits before any submission.
- [x] **Phase 8 — Frontend Dashboard**: Next.js dashboard (Overview, Jobs, Applications, Events, Settings) served at `http://localhost:3000`, proxied to the API through Next.js rewrites.
- [ ] **Phase 9 — Additional ATS Connectors**: Greenhouse/Lever/Ashby/SmartRecruiters discovery connectors exist; a dedicated `generic` fallback adapter is present but application-side (submission) adapters remain Workable/BrowserAgent-generic only.
- [x] **Phase 10 — Reliability Baseline**: matching evaluation dataset + automated eval, local browser regression fixture (Playwright fill-without-submit), minimal GitHub Actions CI, English dashboard UI, an API smoke/performance regression test, and a backup/restore runbook (`docs/runbook.md`). Production-scale load testing remains open (see Roadmap).

## Roadmap

Completed: Phases 0–8 and the Phase 10 reliability baseline above.

Current: manual pipeline operation via the dashboard; German-market discovery adapters (Bundesagentur, Arbeitnow) in regular use.

Future (not started): additional browser/site adapters, larger evaluation dataset, production load testing, architecture simplification, observability.

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
7. MinIO Console: `http://127.0.0.1:9001` (credentials from `.env`: `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`)

> **Note:** MinIO removed the `minio/minio` image from Docker Hub, so `docker-compose.yml` pins `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` instead.

## Security

- Copy `.env.example` to `.env` and replace every `CHANGE_ME_…` placeholder with strong values before starting the stack.
- All API routes except `/health` require the shared `API_KEY` (`X-API-Key` header). The dashboard forwards it server-side via Next.js middleware, so the key never reaches the browser.
- Public ports bind to `127.0.0.1` only; PostgreSQL, Redis, and MinIO's S3 port are not published to the host (use `docker compose exec` for direct access).
- Startup fail-fast: invalid automation settings or weak default secrets (in `ENV=prod`) abort services immediately instead of running misconfigured.
- With `LOG_REDACT_PII=true`, e-mail addresses, phone numbers, and the candidate name are masked in logs.
- Backup/restore procedure: `docs/runbook.md` (including API key rotation).

## Running Tests

Run the complete unit and integration test suite (pure-Python, no Docker services required — DB/Redis/MinIO calls are mocked or use in-memory SQLite):

```bash
python -m venv .venv
.venv\Scripts\pip install -e ./shared pytest pytest-asyncio aiosqlite
.venv\Scripts\python -m pytest -v
```

Lint (must pass for CI):

```bash
python -m ruff check .
```

Run the matching evaluation (offline, uses the production matcher, no LLM key needed):

```bash
.venv\Scripts\python -m pytest tests/evals -v
```

Run the browser regression tests (offline fixture; the Playwright fill test
skips automatically if Chromium is not installed):

```bash
.venv\Scripts\python -m pytest tests/unit/test_browser_regression.py -v
# optional, to run the Playwright part: python -m playwright install chromium
```

Build the frontend dashboard:

```bash
cd services/frontend
npm install
npm run build
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
- `AUTOMATION_MODE=PREPARE_APPLICATION` (the default) fills but never submits. The dashboard's per-application **Submit with Playwright** control requires an explicit confirmation and submits only that selected application in the same browser session used to fill it. `AUTO_SUBMIT=true` + `FULL_AUTO` remain required for unattended submission.
- **Open in Browser** opens the selected application URL in the user's regular browser so the user can complete a CAPTCHA, sign-in, MFA, or a question that cannot be answered from verified profile facts. The agent never bypasses these checks.

### Visible local Playwright helper (Windows)

The Docker browser worker must remain headless, so use the desktop helper when you want Playwright to fill safe fields in a visible browser that remains open for you:

```powershell
.\scripts\install-desktop-runner.ps1
```

After installation, use **Fill with Playwright** in the dashboard's **Applications** tab. It starts a local Chromium session, fills only verified profile answers and available documents, then leaves the browser open. Complete CAPTCHA, sign-in/MFA, and any unanswered questions yourself, then review and submit in that same visible browser window.

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
- `tests/fixtures/application_form.html` covers form parsing, safe-answer resolution, and fill-without-submit locally; live browser-agent runs still exercise real public job boards in `PREPARE_APPLICATION` mode (fill-only, never submits).
- `BROWSER_HEADLESS` must stay `true` in Docker (no X server in the containers); this is now the default in `.env`/`.env.example`.
- Additional ATS *submission* adapters (Greenhouse/Lever/Ashby/SmartRecruiters-specific form flows) are not yet implemented; only discovery-side connectors exist for those sources.
- Matching is keyword-taxonomy based: mandatory requirements outside the taxonomy, non-German/English language requirements, and junior titles are only weakly penalized (pinned by `evals/matching_cases.json` notes).
