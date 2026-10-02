# CAREERFLOW AGENT — FULL REPOSITORY REPAIR & IMPROVEMENT INSTRUCTION

You are operating directly inside the repository:

`devletli/careerflow-agent`

Work on the current branch.

You are NOT here to write a report only.

You are here to inspect the existing code, find the real problems, modify the repository, run tests, and leave the project in a working state.

Act as a:

* Senior Software Architect
* Senior Python Developer
* Senior TypeScript/Next.js Developer
* Playwright automation expert
* AI agent engineer
* QA engineer
* DevOps engineer

Do not blindly rewrite the application.

Preserve existing functionality where it is correct.

Fix root causes instead of adding superficial patches.

---

# 0. ABSOLUTE RULES

Follow these rules during the entire task.

1. Inspect the actual repository before changing anything.
2. Do NOT invent filenames.
3. Do NOT create duplicate services when an existing service already owns the responsibility.
4. Do NOT rewrite working architecture just because you prefer another architecture.
5. Do NOT introduce new frameworks unless absolutely necessary.
6. Do NOT introduce microservices beyond the existing architecture.
7. Do NOT introduce another database.
8. Do NOT introduce another queue.
9. Do NOT remove existing functionality without proving it is dead or incorrect.
10. Every functional change must have a test.
11. Every Playwright change must have a regression test.
12. Never report an application as successful merely because a Playwright click happened.
13. Never automatically retry an application when submission state is ambiguous.
14. Never bypass CAPTCHA, MFA, login walls or security controls.
15. Never expose secrets in logs.
16. Never commit `.env`, credentials, cookies or personal documents.
17. Do not use `any` in TypeScript unless technically unavoidable.
18. Do not swallow exceptions.
19. Do not leave TODO implementations behind.
20. Run tests after implementation.

The repository already contains:

* PostgreSQL
* Redis Streams
* MinIO
* orchestrator
* API
* browser-agent
* Next.js frontend
* job discovery
* matching
* CV generation
* application analysis
* Playwright
* ATS adapters
* tests

Keep these boundaries unless the existing implementation clearly violates them.

---

# 1. FIRST: UNDERSTAND THE REAL ARCHITECTURE

Inspect these directories first:

```text
browser/
db/
profile/
services/
shared/
tests/
docs/
```

Inspect especially:

```text
browser/
browser/site_adapters/

services/api/
services/browser-agent/
services/orchestrator/
services/frontend/
services/application-analyzer/
services/job-discovery/
services/job-matching/
services/cv-generator/

shared/

db/
tests/
```

Also inspect:

```text
README.md
SPEC.md
architecture.md
architecture.md
data-model.md
GuiYama.md
implementation-plan.md
docker-compose.yml
.env.example
Makefile
pytest.ini
mypy.ini
```

If the exact directory names differ, find the corresponding implementation instead of creating a new one.

---

# 2. CREATE A REAL EXECUTION MAP

Trace the real application execution path from the frontend button to the browser.

The important path must be understood as:

```text
Applications UI
      |
      | click "Submit with Playwright"
      v
Frontend API call
      |
      v
FastAPI endpoint
      |
      v
Application service / orchestrator
      |
      v
Application DB record
      |
      v
Browser execution
      |
      v
BrowserAutomationEngine
      |
      v
SiteAdapter
      |
      v
Playwright Page
      |
      v
Form interaction
      |
      v
Submit
      |
      v
Submission verification
      |
      v
Database state
      |
      v
Frontend refresh
```

Find every real function involved.

Write this mapping into:

```text
docs/application-execution-flow.md
```

Do not document imaginary architecture.

Document the actual functions and files.

---

# 3. P0 BUG: PLAYWRIGHT APPLICATION SUBMISSION

The user reports:

> "Playwright ile başvur / Submit with Playwright does not work."

This is the highest-priority issue.

Do NOT assume the problem is the Playwright selector.

Trace the complete flow.

Check:

```text
frontend button
↓
request payload
↓
application_id
↓
API endpoint
↓
application lookup
↓
authorization/validation
↓
execution mode
↓
browser session
↓
browser context
↓
page
↓
site detection
↓
SiteAdapter
↓
form filling
↓
submit
↓
confirmation
↓
database update
```

Find the exact failure.

---

# 4. VERY IMPORTANT: PREPARE VS SUBMIT

The repository currently has a safety architecture where:

```text
PREPARE_APPLICATION
```

means:

```text
fill the form
DO NOT submit
```

and submission requires explicit confirmation / FULL_AUTO + AUTO_SUBMIT.

Do NOT destroy this safety model.

However, the GUI action:

```text
Submit with Playwright
```

must actually enter the correct submit path.

Do NOT accidentally execute:

```text
PREPARE
```

when the user explicitly clicked:

```text
SUBMIT
```

Define an explicit execution intent.

For example:

```python
from enum import Enum


class ApplicationAction(str, Enum):
    PREPARE = "prepare"
    SUBMIT = "submit"
```

If the project already has an equivalent enum/type, use it instead.

The frontend must send an explicit action.

Example:

```typescript
type ApplicationAction = "prepare" | "submit";

async function executeApplication(
  applicationId: string,
  action: ApplicationAction,
) {
  const response = await fetch(
    `/api/v1/applications/${applicationId}/execute`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action }),
    },
  );

  if (!response.ok) {
    throw new Error(
      `Application execution failed: ${response.status}`,
    );
  }

  return response.json();
}
```

Adapt this to the actual frontend API architecture.

---

# 5. NEVER USE GUI TEXT AS THE SOURCE OF TRUTH

Do not determine behavior from a button label.

Bad:

```typescript
if (buttonText.includes("Submit")) {
   ...
}
```

Good:

```typescript
executeApplication(application.id, "submit");
```

The backend must receive an explicit semantic command.

---

# 6. APPLICATION EXECUTION API

Find the existing application execution endpoint.

Do NOT automatically create another endpoint if one already exists.

The endpoint must distinguish:

```text
prepare
submit
```

Conceptually:

```python
class ApplicationExecuteRequest(BaseModel):
    action: Literal["prepare", "submit"]
```

Then:

```python
@router.post(
    "/applications/{application_id}/execute"
)
async def execute_application(
    application_id: UUID,
    request: ApplicationExecuteRequest,
):
    if request.action == "prepare":
        return await application_service.prepare(
            application_id
        )

    if request.action == "submit":
        return await application_service.submit(
            application_id
        )
```

Use the actual existing service architecture.

---

# 7. DO NOT RETURN SUCCESS TOO EARLY

This is critical.

Do NOT do this:

```python
await browser.submit()

return {
    "success": True
}
```

A click is not proof of submission.

Instead:

```python
submission_result = await browser.submit()

verified = await browser.verify_submission(
    submission_result
)

if not verified:
    raise SubmissionVerificationError(
        "Submission could not be verified"
    )

return {
    "success": True,
    "status": "SUBMITTED",
}
```

Adapt this to the actual code.

---

# 8. APPLICATION STATE MACHINE

Find the current application status implementation.

Do not create a second status system.

The state model should support the real lifecycle.

At minimum the conceptual states are:

```python
class ApplicationStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FILLING = "FILLING"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    REQUIRES_HUMAN = "REQUIRES_HUMAN"
```

Use the project's existing naming convention if different.

Do not rename the whole database unnecessarily.

---

# 9. STATE TRANSITIONS MUST BE VALIDATED

Do not allow:

```text
FAILED -> SUBMITTED
```

or:

```text
SUBMITTED -> RUNNING
```

without an explicit reset/retry operation.

Create or improve a transition function.

Example:

```python
ALLOWED_TRANSITIONS = {
    "CREATED": {"QUEUED", "FAILED"},
    "QUEUED": {"RUNNING", "FAILED"},
    "RUNNING": {
        "FILLING",
        "READY_TO_SUBMIT",
        "REQUIRES_HUMAN",
        "FAILED",
    },
    "FILLING": {
        "READY_TO_SUBMIT",
        "REQUIRES_HUMAN",
        "FAILED",
    },
    "READY_TO_SUBMIT": {
        "SUBMITTING",
        "REQUIRES_HUMAN",
    },
    "SUBMITTING": {
        "SUBMITTED",
        "REQUIRES_HUMAN",
        "FAILED",
    },
}
```

Then:

```python
def transition(
    current: str,
    target: str,
) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current, set())

    if target not in allowed:
        raise InvalidApplicationTransition(
            f"{current} -> {target}"
        )
```

Adapt to the actual repository.

---

# 10. PLAYWRIGHT BROWSER LIFECYCLE

This is one of the most important areas to inspect.

Find:

* browser creation
* context creation
* page creation
* session reuse
* storage state
* authentication
* browser shutdown

Ensure:

```text
browser
  └── context
       └── page
            └── application
```

is managed consistently.

Do not create one browser in one service and then expect another service to magically access its page.

If PREPARE and SUBMIT are intentionally separate operations, explicitly define how the session is preserved.

If the current architecture cannot safely preserve a browser session between API calls, do not fake it.

Use one of these explicit strategies:

### Strategy A — same execution session

```text
prepare
 ↓
same execution
 ↓
submit
```

### Strategy B — persistent authenticated context

```text
stored browser state
 ↓
new browser context
 ↓
same login/session
 ↓
application
```

### Strategy C — one-shot execution

```text
submit command
 ↓
open browser
 ↓
authenticate
 ↓
fill
 ↓
submit
 ↓
verify
 ↓
close
```

Choose the strategy that matches the current architecture.

Do NOT introduce global browser objects.

---

# 11. NEVER USE GLOBAL PLAYWRIGHT PAGE OBJECTS

Avoid:

```python
GLOBAL_PAGE = None
```

or:

```python
current_page = global_browser.pages[0]
```

This will break with concurrent applications.

Use explicit execution context:

```python
@dataclass
class BrowserExecutionContext:
    execution_id: str
    browser: Browser
    context: BrowserContext
    page: Page
```

Then pass it explicitly.

---

# 12. BROWSER EXECUTION CONTEXT

If the existing project does not already have an equivalent, implement:

```python
@dataclass
class BrowserExecutionContext:
    execution_id: str
    application_id: str
    browser: Browser
    context: BrowserContext
    page: Page
```

The exact location must be chosen based on the existing browser-agent architecture.

Do not duplicate an existing context class.

---

# 13. SITE ADAPTER ARCHITECTURE

The repository already uses site adapters.

Preserve that architecture.

Conceptually:

```python
class SiteAdapter(Protocol):

    def can_handle(self, page: Page) -> bool:
        ...

    async def prepare(self, page: Page, application: Application):
        ...

    async def submit(self, page: Page):
        ...

    async def verify_submission(self, page: Page) -> bool:
        ...
```

Do not put Workable-specific selectors into the generic browser engine.

Bad:

```python
if "workable" in url:
    await page.locator(...)
```

inside the generic engine.

Good:

```python
adapter = adapter_registry.resolve(page)

await adapter.prepare(page, application)

if action == ApplicationAction.SUBMIT:
    await adapter.submit(page)
    await adapter.verify_submission(page)
```

---

# 14. GENERIC ADAPTER

The generic adapter must remain conservative.

If the page cannot be identified safely:

```python
raise UnsupportedApplicationSite(
    "Unable to safely identify application site"
)
```

Do not blindly click a button named:

```text
Submit
Send
Apply
Continue
```

on an unknown website.

---

# 15. WORKABLE ADAPTER

Inspect the existing Workable adapter.

Verify:

* job URL navigation
* form detection
* required fields
* candidate fields
* CV upload
* cover letter
* consent fields
* submit selector
* confirmation detection

Do not rely exclusively on CSS classes.

Prefer accessible locators:

```python
page.get_by_role("button", name=re.compile(
    r"submit|apply|send",
    re.I,
))
```

But only use this where the site-specific adapter has already established that the page is the expected application page.

---

# 16. GREENHOUSE ADAPTER

Audit:

```text
iframe handling
file upload
required fields
location fields
work authorization
consent
submit button
confirmation
```

If the form is inside an iframe, explicitly locate the frame.

Example:

```python
frame = page.frame_locator(
    "iframe"
)

await frame.get_by_role(
    "button",
    name=re.compile(r"submit", re.I),
).click()
```

Use the actual DOM structure discovered by the adapter.

Do not blindly assume an iframe exists.

---

# 17. LEVER ADAPTER

Audit:

* form detection
* custom questions
* file uploads
* required fields
* submit
* confirmation

Do not make generic assumptions from Greenhouse or Workable.

---

# 18. CAPTCHA / MFA / LOGIN WALL

The system must hard-stop.

Example:

```python
if await detect_captcha(page):
    raise HumanInterventionRequired(
        reason="CAPTCHA detected"
    )
```

Similarly:

```python
if await detect_mfa(page):
    raise HumanInterventionRequired(
        reason="MFA required"
    )
```

Never attempt to solve or bypass these.

The application should become:

```text
REQUIRES_HUMAN
```

not:

```text
FAILED
```

because the system may simply need the user.

---

# 19. FORM FILLING

Audit the current field resolver.

Prefer this priority:

```text
1. label
2. accessible name
3. input name
4. input id
5. placeholder
6. stable data attribute
7. carefully scoped CSS
```

Avoid brittle selectors such as:

```python
page.locator(
    "div:nth-child(7) > div > input"
)
```

unless there is no alternative.

---

# 20. SAFE FORM FILLING

Create helpers where appropriate:

```python
async def fill_if_present(
    page: Page,
    locator,
    value: str | None,
):
    if not value:
        return

    if await locator.count() == 0:
        return

    await locator.fill(value)
```

For required fields:

```python
async def fill_required(
    locator,
    value: str,
    field_name: str,
):
    if not value:
        raise MissingApplicationData(
            field_name
        )

    await locator.fill(value)
```

Do not silently ignore missing required fields.

---

# 21. FILE UPLOADS

Verify the actual CV path before attempting upload.

Example:

```python
path = Path(cv_path)

if not path.exists():
    raise FileNotFoundError(
        f"CV not found: {path}"
    )

await file_input.set_input_files(
    str(path)
)
```

If files are stored in MinIO, explicitly download/materialize the artifact into a temporary file before Playwright upload.

Do not pass a MinIO object key as if it were a local filesystem path.

---

# 22. SUBMISSION VERIFICATION

Every adapter must implement reliable verification.

Potential signals:

```text
URL changed
confirmation page
confirmation heading
success message
application reference number
known success selector
```

Example:

```python
async def verify_submission(page: Page) -> bool:
    confirmation = page.get_by_text(
        re.compile(
            r"application.*received|thank.*apply|success",
            re.I,
        )
    )

    return await confirmation.count() > 0
```

But do not use generic text alone if it could produce false positives.

Prefer site-specific verification.

---

# 23. AMBIGUOUS SUBMISSION

This is critical.

If:

```text
submit clicked
BUT
confirmation not detected
```

DO NOT:

```text
retry automatically
```

Instead:

```text
REQUIRES_HUMAN
```

with:

```text
reason = "Submission result could not be verified"
```

because the application may already have been submitted.

---

# 24. IDEMPOTENCY

Before starting an application:

```python
existing = await repository.find_existing_application(
    candidate_id=candidate_id,
    job_id=job_id,
)
```

If:

```text
SUBMITTED
```

do not submit again.

If:

```text
RUNNING
```

do not start another execution.

If:

```text
REQUIRES_HUMAN
```

offer resume/manual continuation.

If:

```text
FAILED
```

allow retry only when safe.

Use a database uniqueness constraint where appropriate.

---

# 25. DOUBLE-CLICK PROTECTION

The GUI must not allow:

```text
Submit
Submit
Submit
```

within milliseconds.

Implement:

```typescript
const [executing, setExecuting] = useState(false);

async function handleSubmit() {
    if (executing) return;

    setExecuting(true);

    try {
        await executeApplication(
            application.id,
            "submit"
        );
    } finally {
        setExecuting(false);
    }
}
```

Also enforce this server-side.

Frontend protection is NOT sufficient.

---

# 26. EXECUTION ID

Every browser execution should have an ID.

Example:

```python
execution_id = str(uuid4())
```

Store/log:

```text
execution_id
application_id
job_id
action
adapter
step
status
timestamp
```

This allows debugging one failed application without mixing logs from another.

---

# 27. APPLICATION EXECUTION RECORD

If the current database model already supports execution records, use it.

Otherwise add a minimal execution entity/table only if necessary.

Conceptually:

```python
class ApplicationExecution:
    id
    application_id
    action
    status
    current_step
    started_at
    finished_at
    error_code
    error_message
```

Do not add a second parallel state system if the repository already has execution tracking.

---

# 28. STRUCTURED PLAYWRIGHT LOGGING

Use structured logs.

Example:

```python
logger.info(
    "browser.application.step",
    extra={
        "execution_id": execution_id,
        "application_id": application_id,
        "step": "FILLING_FORM",
    },
)
```

Required steps:

```text
STARTING_BROWSER
OPENING_JOB
DETECTING_SITE
AUTHENTICATING
LOADING_FORM
ANALYZING_FORM
FILLING_FORM
UPLOADING_CV
FILLING_QUESTIONS
READY_TO_SUBMIT
SUBMITTING
VERIFYING_SUBMISSION
COMPLETED
FAILED
REQUIRES_HUMAN
```

---

# 29. FAILURE ARTIFACTS

When Playwright fails, capture:

```text
screenshot
current URL
page title
last execution step
adapter
exception
```

Example:

```python
await page.screenshot(
    path=str(
        artifact_dir /
        f"{execution_id}-failure.png"
    ),
    full_page=True,
)
```

Do not expose CV contents or secrets in logs.

Do not commit screenshots.

---

# 30. GUI APPLICATION TABLE

Now inspect the Applications tab.

The user reports that the Applications table does not fit correctly and requires unnecessary page scrolling.

Fix the layout.

The main application viewport should use:

```css
height: 100vh;
overflow: hidden;
```

Conceptually:

```css
.app-shell {
    height: 100vh;
    display: flex;
    flex-direction: column;
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
```

Use the project's actual CSS/Tailwind architecture.

Do not blindly add global CSS.

---

# 31. ONLY TABLE CONTENT SHOULD SCROLL

Bad:

```text
whole browser page scrolls
```

Good:

```text
+-----------------------------------------+
| Header                                  |
+-----------------------------------------+
| Sidebar | Applications                  |
|         |                              |
|         | Filters                       |
|         |------------------------------|
|         | Application table             |
|         |                              ↕|
|         |                              |
+---------+-------------------------------+
```

The table itself can scroll.

The entire dashboard should not.

Apply the same principle to:

```text
Jobs
Applications
Events
Settings
```

where appropriate.

---

# 32. RESPONSIVE APPLICATION TABLE

Audit every column.

Avoid one column expanding the whole table.

Use:

```css
table {
    width: 100%;
    table-layout: fixed;
}
```

For long values:

```css
.cell-truncate {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
```

Use tooltip/details for full values.

Action buttons must remain visible.

---

# 33. APPLICATION ACTIONS

Each application row should have clearly separated actions:

```text
View
Prepare
Submit
Retry
Resume
```

Only display actions that are valid for the current state.

Example:

```text
CREATED
→ Prepare

READY_TO_SUBMIT
→ Submit

RUNNING
→ View progress

REQUIRES_HUMAN
→ Continue manually

FAILED
→ Retry

SUBMITTED
→ View details
```

Do not show Submit for an already submitted application.

---

# 34. GUI STATUS MUST COME FROM BACKEND

Do not calculate application status locally.

Bad:

```typescript
const status =
    isRunning ? "RUNNING" : "COMPLETED";
```

Backend is authoritative.

Frontend only renders the state returned by the API.

---

# 35. AUTO REFRESH

The repository already uses dashboard refresh behavior.

Audit it.

Avoid:

```text
multiple intervals
duplicate polling
memory leaks
requests after component unmount
```

Use cleanup:

```typescript
useEffect(() => {
    const interval = setInterval(
        refreshApplications,
        5000
    );

    return () => clearInterval(interval);
}, []);
```

Use the project's existing data-fetching mechanism if available.

---

# 36. DARK MODE

The GUI is currently perceived as too white.

Implement a real theme system.

Add:

```text
Light
Dark
System
```

if the existing frontend architecture supports it.

Do NOT simply set:

```css
body {
    background: black;
}
```

Create theme tokens.

Example:

```css
:root {
    --bg-primary: #ffffff;
    --bg-secondary: #f6f7f9;
    --surface: #ffffff;
    --surface-hover: #f1f3f5;
    --text-primary: #111827;
    --text-secondary: #6b7280;
    --border: #e5e7eb;
}

.dark {
    --bg-primary: #0b0d10;
    --bg-secondary: #11151a;
    --surface: #171b21;
    --surface-hover: #20252d;
    --text-primary: #f3f4f6;
    --text-secondary: #9ca3af;
    --border: #2a3038;
}
```

Use the existing Tailwind/theme mechanism if present.

Do not hard-code colors in 30 components.

---

# 37. THEME PERSISTENCE

Persist:

```text
light
dark
system
```

using the frontend's existing mechanism.

If no mechanism exists, use localStorage.

Example:

```typescript
const THEME_KEY = "careerflow-theme";

localStorage.setItem(
    THEME_KEY,
    theme
);
```

Avoid hydration mismatch in Next.js.

Implement this correctly for the existing Next.js version.

---

# 38. GUI/API CONTRACT AUDIT

For every Applications action verify:

```text
UI
↓
HTTP method
↓
URL
↓
request body
↓
backend schema
↓
service
↓
DB
↓
response
```

Look specifically for:

* wrong endpoint
* wrong HTTP method
* wrong ID
* wrong field name
* camelCase/snake_case mismatch
* stale frontend API
* response shape mismatch
* errors ignored by frontend

Fix the root cause.

---

# 39. API ERROR HANDLING

Never do:

```typescript
await fetch(url);
setSuccess(true);
```

Check the response.

Use:

```typescript
const response = await fetch(url);

if (!response.ok) {
    const body = await response
        .json()
        .catch(() => null);

    throw new Error(
        body?.detail ??
        `Request failed: ${response.status}`
    );
}
```

Adapt to the project's existing API client.

---

# 40. USER-FACING PLAYWRIGHT ERROR

Do not display:

```text
Internal Server Error
```

when a useful reason exists.

Display something like:

```text
Application could not be completed.

Step:
Form submission

Reason:
Submission could not be verified.

The system did not retry automatically because the application
may already have been submitted.

Please review the application manually.
```

This is especially important for ambiguous submission results.

---

# 41. APPLICATION DETAIL VIEW

If the current UI has an application details view, include:

```text
Application
Company
Job
Status
Execution ID
Action
Current step
Started
Finished
Adapter
Error
Confirmation
```

For debugging:

```text
View execution details
```

Do not expose raw secrets.

---

# 42. PLAYWRIGHT DEBUG MODE

Add/use a controlled configuration such as:

```env
PLAYWRIGHT_HEADLESS=true
```

and optionally:

```env
PLAYWRIGHT_SLOW_MO=0
```

During debugging the developer can use:

```env
PLAYWRIGHT_HEADLESS=false
PLAYWRIGHT_SLOW_MO=250
```

Do not force headed mode in production.

---

# 43. PLAYWRIGHT TIMEOUTS

Do not use arbitrary huge timeouts.

Centralize them.

Example:

```python
PAGE_TIMEOUT_MS = 30_000
ELEMENT_TIMEOUT_MS = 10_000
SUBMISSION_TIMEOUT_MS = 20_000
```

Use the project's configuration mechanism.

---

# 44. DO NOT USE sleep() AS A FIX

Never fix race conditions with:

```python
await asyncio.sleep(5)
```

or:

```typescript
await new Promise(
    resolve => setTimeout(resolve, 5000)
);
```

Prefer:

```python
await page.wait_for_load_state("domcontentloaded")
```

or:

```python
await locator.wait_for(
    state="visible"
)
```

or a meaningful application-specific condition.

---

# 45. FORM REGRESSION TESTS

The repository already has browser fixtures.

Do not discard them.

Expand them.

Test:

```text
prepare fills form
prepare does not submit
submit actually submits
submission confirmation detected
CAPTCHA causes REQUIRES_HUMAN
missing required field causes controlled failure
file upload works
duplicate application prevented
ambiguous submission does not retry
```

Example:

```python
async def test_prepare_does_not_submit(
    page,
    application,
):
    result = await engine.execute(
        application,
        action="prepare",
    )

    assert result.status == "READY_TO_SUBMIT"

    assert not await page.locator(
        "[data-test=confirmation]"
    ).is_visible()
```

Then:

```python
async def test_submit_verifies_confirmation(
    page,
    application,
):
    result = await engine.execute(
        application,
        action="submit",
    )

    assert result.status == "SUBMITTED"
```

Use the existing fixture architecture.

---

# 46. TEST AMBIGUOUS SUBMISSION

Add this regression test.

Simulate:

```text
submit click succeeds
confirmation unavailable
```

Expected:

```python
assert result.status == "REQUIRES_HUMAN"
```

And:

```python
assert result.retryable is False
```

if the existing result model supports such a field.

---

# 47. TEST DUPLICATE SUBMISSION

Test:

```python
application.status = "SUBMITTED"
```

Then execute submit.

Expected:

```python
with pytest.raises(DuplicateApplicationError):
    await service.submit(application.id)
```

Adapt to existing domain behavior.

---

# 48. TEST GUI ACTION

If frontend tests exist, add a test verifying:

```text
Submit button
→ action = "submit"
```

and NOT:

```text
action = "prepare"
```

This is extremely important.

---

# 49. API INTEGRATION TEST

Test:

```http
POST /applications/{id}/execute
```

with:

```json
{
  "action": "submit"
}
```

Verify:

```text
correct application loaded
correct action selected
browser engine receives SUBMIT
status changes correctly
```

---

# 50. FRONTEND BUILD

Run:

```bash
npm run build
```

or the actual project build command.

Fix:

* TypeScript errors
* hydration errors
* lint errors
* unused imports
* invalid API types

Do not disable type checking to make the build pass.

---

# 51. BACKEND TESTS

Run:

```bash
pytest
```

Then specifically:

```bash
pytest tests/unit/
pytest tests/integration/
```

If project-specific commands exist, use them.

---

# 52. MYPY

Run:

```bash
mypy shared/
```

and any configured backend paths.

Do not solve errors by adding:

```python
# type: ignore
```

unless the ignore is genuinely necessary and documented.

---

# 53. PLAYWRIGHT TESTS

Install/use the project's existing browser dependencies.

Run:

```bash
pytest tests/unit/test_browser_regression.py
```

and all browser-related tests.

If tests require Docker, run the appropriate Compose environment.

---

# 54. DOCKER

Run:

```bash
docker compose config
```

Then:

```bash
docker compose up --build
```

Verify:

```text
API
Frontend
Postgres
Redis
MinIO
Browser-agent
```

all start correctly.

Do not change Compose just to hide errors.

---

# 55. REAL GUI MANUAL TEST

After implementation manually test:

```text
Open dashboard
→ Applications
→ select an application
→ Prepare with Playwright
→ verify fields filled
→ verify NOT submitted

Then:

→ Submit with Playwright
→ explicit confirmation if required
→ browser runs
→ submit
→ confirmation detected
→ status becomes SUBMITTED
→ GUI reflects SUBMITTED
```

Also test:

```text
CAPTCHA
MFA
missing CV
duplicate application
browser timeout
unknown site
```

---

# 56. APPLICATION STATE MUST SURVIVE RESTART

Restart services during a running/failed operation.

Verify database state remains consistent.

The application must not depend on in-memory Python variables for authoritative state.

Bad:

```python
active_applications = {}
```

as the source of truth.

Database must remain authoritative.

---

# 57. REDIS IS TRANSPORT, NOT AUTHORITY

If Redis Streams are used:

```text
Redis = transport/event
PostgreSQL = authoritative state
```

Do not store the only copy of application status in Redis.

---

# 58. MINIO IS ARTIFACT STORAGE

Use MinIO for artifacts if that is the existing architecture.

Do not put large CV/document contents into PostgreSQL unless already designed that way.

When Playwright requires a local file:

```text
MinIO
 ↓
temporary local file
 ↓
Playwright upload
 ↓
temporary cleanup
```

Make cleanup reliable:

```python
try:
    ...
finally:
    temp_file.unlink(
        missing_ok=True
    )
```

---

# 59. LOG CORRELATION

All application logs should include:

```text
execution_id
application_id
job_id
```

If the repository already has correlation IDs, reuse them.

Do not create two correlation systems.

---

# 60. CLEANUP DEAD CODE

During the audit identify:

* unused endpoints
* unused frontend components
* duplicated services
* obsolete GUI code
* obsolete Playwright implementations
* old API routes
* dead adapters

Do NOT delete immediately.

Confirm references first.

Then remove only genuinely dead code.

---

# 61. DOCUMENTATION

Update:

```text
README.md
architecture.md
SPEC.md
```

only where the actual implementation changed.

Add:

```text
docs/application-execution-flow.md
```

with the real execution path.

Document:

```text
PREPARE
SUBMIT
REQUIRES_HUMAN
FAILED
SUBMITTED
```

---

# 62. DO NOT OVERENGINEER

Do NOT introduce:

```text
Kafka
Celery
Kubernetes
RabbitMQ
another database
another frontend framework
another ORM
another Playwright framework
another AI framework
```

unless the existing repository absolutely requires it.

The existing architecture is already sufficiently complex.

The objective is:

```text
reliable
observable
testable
simple
```

not:

```text
more services
more abstractions
more code
```

---

# 63. CODE QUALITY

Prefer small functions.

Bad:

```python
async def run_everything():
    ...
```

Good:

```python
await browser_manager.start()
await navigator.open_job()
await adapter.prepare()
await form_filler.fill()
await uploader.upload()
await submitter.submit()
await verifier.verify()
```

Each function should have one responsibility.

---

# 64. EXPLICIT RESULT OBJECT

If the existing code does not already have a good result object, introduce one.

Conceptually:

```python
@dataclass
class ApplicationExecutionResult:
    execution_id: str
    application_id: str
    action: str
    status: str
    current_step: str | None = None
    confirmation_url: str | None = None
    confirmation_reference: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    requires_human: bool = False
```

Use Pydantic if that is the project's established convention.

Do not create duplicate result types.

---

# 65. FRONTEND TYPES MUST MATCH BACKEND

Create/use one canonical response model.

Example:

```typescript
export interface ApplicationExecution {
    executionId: string;
    applicationId: string;
    action: "prepare" | "submit";
    status:
        | "QUEUED"
        | "RUNNING"
        | "FILLING"
        | "READY_TO_SUBMIT"
        | "SUBMITTING"
        | "SUBMITTED"
        | "FAILED"
        | "REQUIRES_HUMAN";
    currentStep?: string;
    errorMessage?: string;
}
```

Use actual backend naming conventions.

Avoid duplicated hand-written types if generated OpenAPI types already exist.

---

# 66. SECURITY

Audit:

```text
application URLs
browser navigation
uploaded files
credentials
cookies
API keys
CVs
cover letters
logs
```

Never log:

```text
password
cookie
API key
authorization header
CV contents
personal document contents
```

Validate external URLs before browser navigation.

---

# 67. FINAL ACCEPTANCE CRITERIA

The task is NOT complete until all of these are true.

### Playwright

```text
[ ] Prepare works
[ ] Prepare does not submit
[ ] Submit enters submit mode
[ ] Correct SiteAdapter selected
[ ] CV upload works
[ ] Required fields work
[ ] CAPTCHA stops automation
[ ] MFA stops automation
[ ] Submission is verified
[ ] Ambiguous submission becomes REQUIRES_HUMAN
[ ] Duplicate submission is prevented
[ ] Browser resources are cleaned up
```

### Backend

```text
[ ] API action is explicit
[ ] state transitions are valid
[ ] database is authoritative
[ ] errors are structured
[ ] execution_id exists
[ ] logs are correlated
```

### Frontend

```text
[ ] Applications table fits viewport
[ ] only table content scrolls
[ ] no unnecessary page scrolling
[ ] Submit cannot be double-clicked
[ ] status is backend-driven
[ ] errors are understandable
[ ] dark mode works
[ ] light mode works
[ ] theme persists
```

### Tests

```text
[ ] unit tests pass
[ ] integration tests pass
[ ] browser regression tests pass
[ ] frontend build passes
[ ] mypy passes
[ ] docker compose config passes
```

---

# 68. REQUIRED IMPLEMENTATION REPORT

At the end provide a concise report with exactly:

## 1. ROOT CAUSE

Explain the actual cause of the Playwright submit problem.

Not:

```text
"Playwright had a problem."
```

Instead:

```text
Frontend sent X
Backend expected Y
which caused Z
```

if that is what you discover.

## 2. FILES MODIFIED

```text
path/to/file.py
path/to/component.tsx
...
```

For every file:

```text
what changed
why
```

## 3. FILES CREATED

Exact paths.

## 4. FILES REMOVED

Only if applicable.

## 5. DATABASE CHANGES

Exact migration and fields.

## 6. PLAYWRIGHT CHANGES

Explain:

```text
browser lifecycle
session
adapter
form filling
submit
verification
failure handling
```

## 7. GUI CHANGES

Explain:

```text
Applications layout
scrolling
dark mode
actions
status
```

## 8. TESTS RUN

Give exact commands and results.

## 9. REMAINING PROBLEMS

Be honest.

Do not claim production readiness if real ATS behavior has not been verified.

## 10. MANUAL TEST

Give me the exact steps I should perform manually to verify the feature.

---

# 69. IMPORTANT FINAL INSTRUCTION

Do not stop after making the code compile.

Do not stop after the frontend looks correct.

Do not stop after a unit test passes.

The real acceptance criterion is:

```text
USER CLICKS
"SUBMIT WITH PLAYWRIGHT"

        ↓

CORRECT APPLICATION

        ↓

CORRECT BROWSER SESSION

        ↓

CORRECT SITE ADAPTER

        ↓

FORM FILLED

        ↓

CV UPLOADED

        ↓

SUBMIT EXECUTED

        ↓

ACTUAL CONFIRMATION DETECTED

        ↓

DATABASE = SUBMITTED

        ↓

GUI = SUBMITTED
```

If any part of this chain is not true, continue debugging.

Do not fake success.

Do not hide errors.

Do not add superficial retries.

Fix the root cause.

---

# 70. AFTER EVERYTHING WORKS

Run:

```bash
git status
git diff --stat
git diff
```

Review the complete diff.

Remove:

* debug prints
* temporary files
* screenshots
* hardcoded credentials
* unnecessary comments
* unused imports
* dead code
* temporary test bypasses

Then run the complete relevant test suite again.

Only after all of this is complete consider the task finished.
