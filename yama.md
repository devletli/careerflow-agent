Review your latest implementation at commit:

`b1b765af550ebecdd14dd0118df78acb2bf1a684`

Do NOT add unrelated features.

Fix the following concrete problems.

# P0 — FIX APPLICATION ACTION SEMANTICS

The current frontend maps all actions to:

```jsx
onClick={() => onSubmit(a)}
```

This is WRONG.

Prepare, Submit, Retry and Continue Manually must NOT use the same implicit action.

Implement explicit semantic actions.

Use this model:

```javascript
const APPLICATION_ACTIONS = {
    PREPARE: "prepare",
    SUBMIT: "submit",
    RETRY: "retry",
    CONTINUE: "continue",
};
```

Change the frontend so the calls are explicitly:

```jsx
onClick={() => onExecute(a, "prepare")}
```

```jsx
onClick={() => onExecute(a, "submit")}
```

```jsx
onClick={() => onExecute(a, "retry")}
```

```jsx
onClick={() => onExecute(a, "continue")}
```

Do NOT use button text to determine the action.

Trace the call all the way to the backend.

The backend must receive the action explicitly.

Example:

```json
{
    "action": "submit"
}
```

The backend must then call the corresponding application operation.

Do not map all four actions to the same browser execution.

---

# P0 — FIX SUBMISSION CLICK / CONFIRMATION LOGIC

Current implementation:

```python
await button.click()
await page.wait_for_load_state(
    "networkidle",
    timeout=15000
)
```

followed by:

```python
except Exception:
    return {
        "clicked": False,
        "confirmed": False
    }
```

is unsafe.

If the click succeeds but networkidle times out, the implementation currently reports `clicked=False`.

Fix this.

Separate:

```text
click_success
confirmation_success
```

Example:

```python
async def _click_submit(self, page):
    try:
        button = await self._find_submit_button(page)

        if button is None:
            return {
                "clicked": False,
                "confirmed": False,
                "error": "SUBMIT_BUTTON_NOT_FOUND",
            }

        await button.click()

        # The click itself succeeded.
        clicked = True

        # Do NOT require networkidle as proof of submission.
        confirmation = await self._wait_for_confirmation(
            page,
            timeout_ms=15000,
        )

        return {
            "clicked": True,
            "confirmed": confirmation is not None,
            "confirmation": confirmation,
        }

    except Exception as exc:
        logger.exception("Submit execution failed")

        return {
            "clicked": False,
            "confirmed": False,
            "error": str(exc),
        }
```

Use the project's actual types and architecture.

The important rule:

A timeout AFTER a successful click must NOT convert the click into `clicked=False`.

---

# P0 — MAKE CONFIRMATION DETECTION ROBUST

Do not use generic:

```text
success
thank you
```

as universal confirmation signals.

The current implementation:

```python
text=~"application received|thank you for applying|success|submission confirmed"
```

is too broad.

Remove generic `"success"`.

Implement:

```python
async def _wait_for_confirmation(
    self,
    page,
    timeout_ms: int = 15000,
):
    ...
```

Poll/wait for actual confirmation signals.

At minimum:

1. known confirmation URL
2. known confirmation reference
3. explicit application-received message
4. adapter-specific confirmation

Do not treat arbitrary `"success"` text as proof.

---

# P0 — ADAPTER-SPECIFIC CONFIRMATION

If the SiteAdapter architecture already exists, confirmation must preferably be delegated to the adapter.

Conceptually:

```python
confirmation = await adapter.verify_submission(page)

if confirmation:
    status = SUBMITTED
else:
    status = REQUIRES_HUMAN
```

Do not make the generic browser engine responsible for all ATS-specific confirmation rules.

Workable, Greenhouse and Lever may have different confirmation behavior.

Keep generic fallback detection conservative.

---

# P0 — ACTION-BASED GUI STATE

Replace:

```javascript
const availableActions = useCallback(() => {
    const a = applications?.find(
        x => x.id === submittingApplicationId
    );
    ...
}, [applications, submittingApplicationId]);
```

This is incorrect because available actions must be calculated for EACH application row.

Implement:

```javascript
function getAvailableActions(application) {
    switch (application.status) {
        case "CREATED":
            return ["prepare"];

        case "READY_TO_SUBMIT":
            return ["submit"];

        case "RUNNING":
            return ["view"];

        case "REQUIRES_HUMAN":
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

Then inside the row:

```jsx
const actions = getAvailableActions(a);
```

Do not use `submittingApplicationId` to determine which actions exist.

---

# P1 — FIX RETRY SEMANTICS

Retry must NOT blindly submit again.

Define retry behavior server-side.

At minimum:

```text
FAILED before submit
    -> retry may be allowed

AMBIGUOUS SUBMISSION
    -> retry forbidden

REQUIRES_HUMAN because submission is uncertain
    -> retry forbidden

SUBMITTED
    -> retry forbidden

CAPTCHA
    -> human intervention

MFA
    -> human intervention
```

Use:

```python
retryable = False
```

as the safe default.

Only explicitly mark safe errors retryable.

---

# P1 — FIX CONTINUE MANUALLY

Current:

```jsx
onClick={() => onSubmit(a)}
```

is wrong.

Use:

```jsx
onClick={() => onExecute(a, "continue")}
```

Backend must implement the actual semantics.

If "continue manually" means opening the browser at the saved state, implement that.

If the architecture cannot safely resume a browser session, do NOT pretend it can.

Instead provide a clear manual continuation workflow.

---

# P1 — FIX CSS SYNTAX

The previous implementation contains invalid CSS with whitespace between numeric values and units.

Examples currently introduced:

```css
height: 100 vh;
```

```css
@media (max-width: 700 px)
```

```css
border-left: 1 px solid var(--border);
```

```css
minmax(220 px, 1 fr)
```

Fix to:

```css
height: 100vh;
```

```css
@media (max-width: 700px)
```

```css
border-left: 1px solid var(--border);
```

```css
grid-template-columns:
    repeat(auto-fit, minmax(220px, 1fr));
```

Search the ENTIRE modified CSS file for the same mistake.

Do not only fix these four examples.

---

# P1 — FIX MOBILE TABLE OVERFLOW

Current:

```css
@media (max-width: 700px) {
    .table-wrapper {
        overflow: hidden;
    }
}
```

This can hide table content.

Use a proper responsive behavior.

Prefer:

```css
.table-wrapper {
    overflow: auto;
}
```

and on mobile:

```css
.table-wrapper {
    overflow-x: auto;
    overflow-y: auto;
}
```

Do not hide required application columns.

---

# P1 — APPLY STICKY ACTION CLASS

You created:

```css
.actions-sticky
```

but the Applications table currently uses:

```jsx
className="application-actions"
```

Either:

1. use `actions-sticky` on the action cell, or
2. remove the unused CSS.

Do not leave dead CSS.

If sticky actions are desired:

```jsx
<td
    className="application-actions actions-sticky"
>
```

Verify it works with the table wrapper.

---

# P1 — REVIEW OLD ai-job-agent://prepare

The frontend still contains:

```jsx
href={`ai-job-agent://prepare?application_id=${a.id}`}
```

Audit whether this protocol is still part of the current architecture.

If the application now uses the backend/browser-agent API, remove the obsolete protocol.

Do NOT remove it if it is genuinely required by the current desktop/browser integration.

If retained, document exactly why.

---

# P2 — CLEAN UNUSED CODE

Check:

```python
import time
```

and:

```javascript
const [actionMessage, setActionMessage] =
    useState("");
```

If unused, remove them.

Run lint/type checking to find additional unused code.

---

# P1 — MOVE SHARED EXECUTION RESULT IF NECESSARY

Review:

```python
class ExecutionResult:
```

inside:

```text
services/browser-agent/app/engine.py
```

If this result is consumed only inside browser-agent, leave it.

If API/orchestrator/frontend contracts need it, move the canonical contract to the existing shared contracts package.

Do not create duplicate result models.

---

# P0 — ADD REGRESSION TESTS

Add tests for:

### 1. Prepare

```text
prepare
→ fills
→ does NOT submit
```

### 2. Submit

```text
submit
→ click
→ confirmation
→ SUBMITTED
```

### 3. Click succeeds but networkidle times out

Expected:

```text
clicked = true
```

NOT:

```text
clicked = false
```

### 4. Ambiguous submission

```text
clicked = true
confirmation = false
```

Expected:

```text
REQUIRES_HUMAN
retryable = false
```

### 5. Duplicate submission

```text
SUBMITTED
→ submit
```

must be rejected.

### 6. GUI action contract

Verify:

```text
Prepare → action=prepare
Submit → action=submit
Retry → action=retry
Continue → action=continue
```

Do not merely test that buttons render.

---

# P0 — VERIFY REAL API FLOW

Trace the frontend action to the actual backend.

Do not stop at the component.

Prove:

```text
button
↓
onExecute(a, action)
↓
HTTP request
↓
request body
↓
FastAPI schema
↓
service
↓
browser engine
↓
correct action
```

If any layer drops the action value, fix it.

---

# P0 — DO NOT CLAIM SUCCESS WITHOUT CONFIRMATION

The only valid successful submission state is:

```text
click succeeded
+
submission confirmation verified
```

Then:

```text
Application = SUBMITTED
```

Otherwise:

```text
click failed
→ FAILED
```

or:

```text
click succeeded
+
confirmation uncertain
→ REQUIRES_HUMAN
```

Never:

```text
click succeeded
→ SUBMITTED
```

without verification.

---

# FINAL VALIDATION

Run:

```bash
git diff
```

Then:

```bash
pytest
```

and the project's browser regression tests.

Run frontend build/lint.

Verify CSS compilation.

Verify the Applications UI manually.

Most importantly manually verify:

```text
CREATED
→ Prepare
→ READY_TO_SUBMIT
→ Submit
→ browser opens
→ correct form
→ click
→ confirmation
→ SUBMITTED
```

Do not mark this task complete until this exact flow is correctly represented in code and tests.

At the end report:

1. files changed
2. exact root causes
3. tests added
4. tests executed
5. remaining limitations
