You are working inside the EXISTING local repository:

careerflow-agent

This is an incremental UI improvement.

The user will review and commit the changes manually.

## GIT RULE

DO NOT:

* git commit
* git push
* reset
* rebase
* rewrite history
* create branches

Only modify the local working tree.

---

# OBJECTIVES

Implement TWO focused improvements:

## 1. DARK MODE / LIGHT MODE TOGGLE

The current GUI is visually too white.

Add a user-facing theme toggle that allows:

Light mode
↔
Dark mode

The toggle should be accessible from the existing dashboard header/navigation/settings area.

Prefer a simple sun/moon button with tooltip/title.

Example:

```tsx
<button
  type="button"
  onClick={toggleTheme}
  aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
  title={isDark ? "Switch to light mode" : "Switch to dark mode"}
>
  {isDark ? <Sun /> : <Moon />}
</button>
```

IMPORTANT:

Before implementing this, inspect whether the project already uses:

* Tailwind dark mode
* CSS variables
* next-themes
* ThemeProvider
* localStorage
* system theme detection

If an existing theme mechanism exists, USE IT.

Do NOT introduce a second theme system.

If no theme system exists, implement the smallest maintainable solution.

---

# DARK THEME IMPLEMENTATION

Prefer semantic theme variables instead of hardcoding black/white everywhere.

For example, if the project uses CSS variables:

```css
:root {
  --background: #ffffff;
  --foreground: #171717;
  --card: #ffffff;
  --card-foreground: #171717;
  --border: #e5e7eb;
  --muted: #f3f4f6;
}

.dark {
  --background: #0b0b0b;
  --foreground: #f5f5f5;
  --card: #151515;
  --card-foreground: #f5f5f5;
  --border: #2a2a2a;
  --muted: #1f1f1f;
}
```

Adapt the actual values to the existing design.

DO NOT make the entire interface pure `#000000` unless the existing design already uses that aesthetic.

Prefer a professional dark dashboard:

background ≈ #0b0b0b
cards ≈ #151515
borders ≈ #292929
primary text ≈ #f5f5f5
secondary text ≈ #a3a3a3

The exact values are not mandatory; consistency is.

---

# THEME PERSISTENCE

The user's selection should survive page reload.

If the project already uses a theme library, use its persistence mechanism.

Otherwise use localStorage or the project's existing client-side preference mechanism.

Do not introduce a backend setting for this.

The theme is a local UI preference.

---

# AVOID FLASH OF WRONG THEME

If using Next.js/server rendering:

Do not introduce a noticeable:

dark → white → dark

flash on page load.

If the project already uses `next-themes`, configure it correctly.

If implementing manually, use the smallest SSR-safe approach available in the current architecture.

Do not convert the whole application to a new rendering architecture.

---

# DARK MODE COVERAGE

The theme must apply consistently to:

* dashboard background
* sidebar
* header
* tabs
* cards
* tables
* forms
* inputs
* buttons
* dropdowns
* dialogs/modals
* status badges
* Applications
* Documents
* Jobs
* Events
* Settings
* empty states
* loading states
* error states

Do not leave large white rectangles in dark mode.

Avoid isolated hard-coded classes such as:

```text
bg-white
text-black
border-gray-200
```

when they prevent the dark theme from working.

Replace them with the project's existing semantic/theme mechanism.

Do not blindly replace every `white` string globally.

Inspect each component.

---

# 2. NO HORIZONTAL SCROLLING IN DASHBOARD TABS

The user explicitly does NOT want horizontal scrolling inside tabs.

This applies especially to:

* Applications
* Jobs
* Documents
* Events
* Settings

The primary dashboard experience should fit the viewport.

IMPORTANT:

Do NOT solve this by:

```css
overflow-x: auto;
```

on the tab.

That was an earlier approach and is not desired here.

Do NOT make the user drag a table horizontally.

Instead make the content responsive.

---

# APPLICATIONS — RESPONSIVE TABLE

Inspect the actual Applications table.

Determine its actual columns.

Do not assume column names.

The table should fit approximately:

1440×900
1280×800
1024×768

without horizontal scrolling.

---

# RESPONSIVE TABLE STRATEGY

Use the existing design system.

If the table currently has too many columns, prioritize information.

Example hierarchy:

PRIMARY:

* Job / Position
* Company
* Status
* Match

SECONDARY:

* Created date
* Documents
* Application metadata

ACTIONS:

* View
* Open
* Analyze
* Browser actions

Do NOT remove existing functionality.

Instead change presentation.

For example, rather than:

```text
Company | Job Title | Status | Match | Created | CV | Cover Letter | Browser | Submit
```

which is too wide,

use:

```text
Company / Job
Status
Match
Updated
Actions
```

and place secondary information inside the Job/Application details view or compact metadata.

ONLY do this if the current UI genuinely contains too many columns.

Do not remove data from the backend.

---

# TABLE CELL RULES

Long text must not force the table wider.

For example:

```tsx
<td className="min-w-0">
  <div className="min-w-0">
    <div className="truncate font-medium">
      {job.title}
    </div>
    <div className="truncate text-sm text-muted-foreground">
      {company.name}
    </div>
  </div>
</td>
```

Use:

```text
truncate
overflow-hidden
text-ellipsis
whitespace-nowrap
min-w-0
```

where appropriate.

For information that should wrap instead of truncate:

```tsx
<div className="break-words">
  {description}
</div>
```

Do NOT allow URLs, artifact paths or long error messages to determine the table width.

---

# ACTION BUTTONS

Actions must remain usable without expanding the table.

Use compact buttons.

Example:

```tsx
<div className="flex items-center justify-end gap-1.5 flex-wrap">
  <Button size="sm">View</Button>
  <Button size="sm">Analyze</Button>
  <Button size="sm">Open</Button>
</div>
```

If there are too many actions, use an existing dropdown/menu component:

```text
[View] [⋯]
```

with:

* Analyze
* Generate CV
* Generate Cover Letter
* Browser actions
* etc.

Do NOT remove functionality.

Do NOT create extremely tiny unreadable buttons.

---

# APPLICATIONS MOBILE / NARROW VIEW

At narrow widths, a table may no longer be the correct representation.

If the current application already has a card/list component, use it.

Otherwise, if necessary, introduce a responsive presentation:

Desktop:

```text
Applications table
```

Narrow:

```text
Application cards
```

Example:

```tsx
<div className="grid gap-3 md:hidden">
  {applications.map(application => (
    <ApplicationCard
      key={application.id}
      application={application}
    />
  ))}
</div>

<div className="hidden md:block">
  <ApplicationsTable
    applications={applications}
  />
</div>
```

ONLY introduce this if the current table genuinely cannot fit without destroying readability.

Do not build a second completely independent application implementation if the existing components can be reused.

---

# DASHBOARD WIDTH

Inspect the dashboard shell.

The intended structure should conceptually be:

```tsx
<div className="min-h-screen w-full">
  <Sidebar />

  <main className="min-w-0 flex-1">
    <Header />

    <div className="w-full min-w-0 px-4 sm:px-6 lg:px-8">
      <TabContent />
    </div>
  </main>
</div>
```

Adapt to the actual implementation.

The important properties are:

```text
main:
flex: 1
min-width: 0

content:
width: 100%
min-width: 0
```

Do NOT introduce a restrictive:

```text
max-w-*
```

on the main dashboard content unless the existing design explicitly requires it.

---

# OTHER TABS

Perform the same responsive inspection for:

## Jobs

Cards/list must fit viewport.

## Documents

Document rows/cards must fit.

Do NOT show raw internal artifact paths as wide text.

Use:

```text
Document name
Type
Created
Status
[View] [Download]
```

with long paths hidden from normal presentation.

## Events

Long event messages must wrap/truncate.

## Settings

Forms should fit the content area without horizontal overflow.

---

# NO PAGE-LEVEL HORIZONTAL OVERFLOW

After implementation, verify:

```js
document.documentElement.scrollWidth <= window.innerWidth
```

for the main dashboard screens.

If false, find the element causing the overflow.

Do NOT simply hide it with:

```css
overflow-x: hidden;
```

That would hide the bug.

Find the actual overflowing element.

---

# RESPONSIVE ACCEPTANCE TEST

Check the application at:

### Desktop

1440 × 900

### Laptop

1280 × 800

### Small desktop/tablet

1024 × 768

### Mobile

390 × 844

At every size verify:

* no page-level horizontal scrolling
* no important button is clipped
* Applications fits
* Documents fits
* Jobs fits
* Events fits
* Settings fits
* sidebar/navigation remains usable
* theme toggle remains accessible

---

# IMPLEMENTATION REQUIREMENT

Do not merely describe the changes.

Actually modify the existing code.

For every important change identify:

1. Actual file path.
2. Actual component/function.
3. Existing problematic code.
4. Replacement implementation.
5. Why the change fixes the problem.

For example:

```text
FILE:
frontend/src/.../Applications.tsx

COMPONENT:
ApplicationsTable

PROBLEM:
The table has 9 fixed-width columns and its parent uses
overflow-x-auto.

CHANGE:
Remove fixed column widths, consolidate secondary metadata,
make title/company cell flexible, and move secondary actions
into the existing dropdown.

RESULT:
Applications fits the available dashboard width without
horizontal scrolling.
```

Use the REAL paths and REAL components discovered in the repository.

Do NOT invent filenames.

---

# TESTING

Run the project's existing:

* lint
* typecheck
* build
* frontend tests
* browser tests

Then manually/browser-test:

Applications
Documents
Jobs
Events
Settings

at all four viewport sizes.

Also test:

1. Start in light mode.
2. Switch to dark.
3. Reload.
4. Confirm dark mode persists.
5. Switch back to light.
6. Reload.
7. Confirm light mode persists.

Check browser console for errors.

Check network requests for failed API calls.

---

# DO NOT OVERENGINEER

Do NOT:

* add a new frontend framework
* add a new state management library
* rewrite the dashboard
* create a new design system
* introduce a backend theme API
* add unnecessary dependencies
* redesign the entire application
* remove application functionality
* hide overflow globally
* solve table problems with horizontal scrolling

Use the existing architecture.

---

# FINAL REPORT

Return:

## Root causes found

Especially:

* why Applications was too narrow
* which elements caused overflow
* whether other tabs had the same issue

## Files changed

Actual paths.

## Implementation

For each file explain the actual code/component change.

## Theme

Explain:

* existing theme mechanism reused or new minimal mechanism
* persistence
* dark-mode coverage

## Responsive behavior

Explain how Applications and other tabs now fit without horizontal scrolling.

## Tests

Exact commands and results.

## Manual viewport checks

1440×900
1280×800
1024×768
390×844

## Remaining issues

Only real unresolved issues.

## Git

Confirm:

NO commit.
NO push.
Changes remain local and uncommitted.
