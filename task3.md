# CAREERFLOW — CONTINUOUS JOB DISCOVERY + GLOBAL MATCH SCORE RANKING

Repository:

`https://github.com/devletli/careerflow-agent`

Act as:

* Senior Software Architect
* Senior Backend Engineer
* Senior Data Engineer
* Senior DevOps Engineer
* Senior PostgreSQL Engineer

## PRIMARY GOAL

The current system must NOT behave as:

```text
Search jobs
    ↓
100 jobs
    ↓
STOP
```

The desired behavior is:

```text
Continuous job discovery
        ↓
Hundreds / thousands of jobs
        ↓
Deduplicate
        ↓
Persist ALL unique jobs
        ↓
Calculate match score
        ↓
Persist match score
        ↓
Jobs UI sorts ALL jobs by match score DESC
        ↓
Pagination only controls how many rows are displayed
```

The number `100` may be a UI page size.

It must NEVER be a global discovery limit.

---

# 1. FIRST AUDIT THE CURRENT IMPLEMENTATION

Before changing anything inspect the current repository.

Search for ALL occurrences of:

```text
limit
LIMIT
100
page_size
pageSize
offset
pagination
jobs
job_matches
match_score
score
discovery
search
scrape
source
max_pages
max_results
```

Especially inspect:

```text
services/api/app/routers/jobs.py
services/api/app/routers/job_matches.py
services/api/app/
shared/db/models.py
db/migrations/
services/frontend/app/components/tabs/JobsTab.js
services/frontend/app/
workers/
automation/
scripts/
docker-compose.yml
```

Also inspect the actual discovery implementation.

DO NOT assume that the 100 limit is only in the frontend.

Find every place where discovery can stop after 100 results.

---

# 2. DISTINGUISH THREE DIFFERENT LIMITS

These concepts MUST NOT be mixed.

## A. Discovery batch size

Example:

```text
100 jobs per API/search request
```

This is allowed.

## B. Discovery session/page limit

Example:

```text
source page 1
source page 2
source page 3
...
```

This should continue according to configured safety limits.

## C. UI page size

Example:

```text
100 rows visible in the Jobs table
```

This is also allowed.

The bug to eliminate is:

```text
discovery batch size = 100
AND
system stops discovery after first batch
```

That must NOT happen.

---

# 3. DATABASE IS THE COMPLETE JOB HISTORY

Every unique discovered job must be persisted.

If discovery finds:

```text
1,000 jobs
```

the database should contain all 1,000 unique jobs.

If later it finds:

```text
2,000 additional jobs
```

the database should contain:

```text
3,000 unique jobs
```

assuming no duplicates.

Do NOT delete old jobs merely because they are not on the latest search page.

---

# 4. DEDUPLICATION

Before inserting a discovered job:

calculate a stable fingerprint.

Use the repository's existing fingerprint implementation if available.

Do NOT create another incompatible fingerprint system.

Preferred conceptual behavior:

```python
fingerprint = build_job_fingerprint(
    company=normalized_company,
    title=normalized_title,
    location=normalized_location,
    url=canonical_url,
)
```

Then:

```python
existing = find_job_by_fingerprint(fingerprint)

if existing:
    update_existing_job_if_needed(existing)
else:
    create_job(...)
```

Do NOT create duplicate rows when the same job is returned by multiple search pages or sources.

---

# 5. DO NOT DEDUP BY TITLE ONLY

This is WRONG:

```python
unique_key = job.title
```

These are different:

```text
Senior DevOps Engineer — Bosch Berlin
Senior DevOps Engineer — Siemens Berlin
Senior DevOps Engineer — BMW Munich
```

Use the repository's existing canonical fingerprint strategy.

---

# 6. CONTINUOUS DISCOVERY

Discovery should iterate through available result pages/batches.

Conceptually:

```python
page = 1

while True:
    results = search_source(
        query=query,
        page=page,
        page_size=BATCH_SIZE,
    )

    if not results:
        break

    process_results(results)

    if len(results) < BATCH_SIZE:
        break

    page += 1
```

However:

DO NOT implement an uncontrolled infinite loop.

Use configuration:

```python
DISCOVERY_BATCH_SIZE = 100
DISCOVERY_MAX_PAGES_PER_RUN = 50
DISCOVERY_MAX_RUNTIME_SECONDS = 300
```

Use whichever configuration system already exists in the repository.

Do NOT hard-code these values inside business logic.

---

# 7. IMPORTANT: MAX PAGES IS NOT MAX JOBS

This is acceptable:

```text
BATCH_SIZE = 100
MAX_PAGES = 50
```

because it means:

```text
up to 5,000 results per source/run
```

It does NOT mean:

```text
100 total jobs
```

If the source has fewer results, stop naturally.

If the source has more results than the safety limit, stop the CURRENT RUN and continue on the NEXT scheduled run.

Do not lose the continuation position if the source supports pagination.

---

# 8. PAGINATION CURSOR

If a source provides:

```text
next_page
next_cursor
offset
continuation_token
```

use it.

Prefer cursor-based pagination when the source supports it.

Conceptually:

```python
cursor = None

while True:
    response = source.search(
        query=query,
        cursor=cursor,
        limit=BATCH_SIZE,
    )

    process(response.jobs)

    cursor = response.next_cursor

    if not cursor:
        break
```

Do NOT assume page numbers if the provider uses cursors.

---

# 9. DISCOVERY STATE

If the existing system has a discovery/source state model, extend it instead of introducing another unrelated scheduler.

Track:

```text
source
query
cursor/page
last_run_at
last_success_at
jobs_found
jobs_inserted
jobs_updated
```

If appropriate, persist:

```text
discovery_runs
```

or use the existing:

```text
automation_runs
pipeline_events
```

Do NOT create redundant tables if the existing infrastructure already provides equivalent functionality.

---

# 10. MATCH SCORE MUST BE PERSISTED

The match score must NOT be calculated only in the frontend.

It must be calculated by the backend/job matching pipeline and persisted.

The existing:

```text
job_matches
```

table should be reused if it already stores:

```text
job_id
profile_id
match_score
```

Do NOT create a duplicate score table.

---

# 11. GLOBAL MATCH SCORE

For the current user/profile:

every unique job should have a match score where possible.

Example:

```text
Job A → 98
Job B → 91
Job C → 73
Job D → 97
```

The database query should return:

```text
A 98
D 97
B 91
C 73
```

NOT:

```text
A 98
B 91
C 73
```

because they happened to be the first three discovered.

---

# 12. SORT IN DATABASE

Do NOT sort thousands of jobs in React.

Use SQL/database ordering.

Conceptually:

```sql
SELECT
    j.*,
    jm.match_score
FROM jobs j
LEFT JOIN job_matches jm
    ON jm.job_id = j.id
    AND jm.profile_id = :profile_id
ORDER BY
    jm.match_score DESC NULLS LAST,
    j.created_at DESC,
    j.id DESC
LIMIT :page_size
OFFSET :offset;
```

Adapt this to the actual schema.

IMPORTANT:

Use a deterministic secondary sort.

Recommended:

```text
match_score DESC
created_at DESC
id DESC
```

This prevents unstable pagination.

---

# 13. NULL SCORE BEHAVIOR

Jobs without a calculated score should NOT appear above scored jobs.

Use:

```sql
ORDER BY match_score DESC NULLS LAST
```

Conceptually:

```text
98%
97%
96%
...
51%
NULL
NULL
```

This is mandatory.

---

# 14. PROFILE-SPECIFIC SCORE

Do not assume a global score if the repository supports multiple profiles.

The score must be associated with the correct profile.

Use:

```text
job_matches.profile_id
```

or the equivalent existing relationship.

The Jobs page must query the active/current profile.

Do NOT mix scores between profiles.

---

# 15. NEW JOB FLOW

When a new job is discovered:

```text
NEW JOB
   ↓
normalize
   ↓
deduplicate
   ↓
persist job
   ↓
calculate match score
   ↓
persist job_match
   ↓
available in ranking
```

Do not wait until the frontend opens the Jobs page to calculate the score.

---

# 16. EXISTING JOB FLOW

When an existing job is discovered again:

```text
existing job
    ↓
update metadata if necessary
    ↓
do NOT create duplicate
    ↓
recalculate score only if required
```

Do not reset:

```text
application
notes
manual status
documents
```

just because the job was rediscovered.

---

# 17. IMPORTANT: DO NOT DESTROY USER STATE

Suppose:

```text
Job:
Bosch Senior DevOps

User status:
INTERESTED

Application:
APPLIED

Documents:
CV v4
Cover Letter v2
```

The same job is discovered again.

The discovery process MUST NOT reset:

```text
INTERESTED
APPLIED
CV v4
Cover Letter v2
```

Discovery is not allowed to overwrite human workflow state.

---

# 18. JOB UI — REMOVE GLOBAL 100 LIMIT

The Jobs UI may show:

```text
100 rows
```

but this is page size only.

The UI must display:

```text
Showing 1–100 of 8,742 jobs
```

and provide:

```text
Previous
1
2
3
...
88
Next
```

or equivalent pagination.

Do NOT load all 8,742 rows into React.

---

# 19. PAGE SIZE SELECTOR

Add:

```text
Rows:
[50]
[100]
[250]
[500]
```

Default:

```text
100
```

Do NOT provide "All" if it could cause a huge browser payload.

If "All" already exists, remove it unless the dataset is safely bounded.

---

# 20. TOTAL COUNT

The API must provide total count.

Example:

```json
{
  "items": [...],
  "page": 1,
  "page_size": 100,
  "total": 8742,
  "total_pages": 88
}
```

Use a separate efficient count query if necessary.

Do NOT calculate total from:

```text
items.length
```

because that is only the current page.

---

# 21. DEFAULT JOB SORT

The default Jobs view MUST be:

```text
Match Score DESC
```

not:

```text
created_at DESC
```

The user wants the best matching jobs first.

Secondary ordering:

```text
created_at DESC
id DESC
```

---

# 22. SORT OPTIONS

Keep match score as default.

Optionally support:

```text
Match score ↓
Newest ↓
Updated ↓
```

Do not remove match-score sorting.

When the user changes sorting, preserve pagination correctly.

---

# 23. FILTERS

Jobs page should support:

```text
All
Interested
Shortlisted
Applied
Archived
```

only if the corresponding user lifecycle state exists.

Do NOT confuse:

```text
discovery status
```

with:

```text
user status
```

If the current Job model uses an operational `status`, do not repurpose it blindly.

---

# 24. SEARCH

Add server-side search where practical.

Example:

```text
Search:
"DevOps AWS Kubernetes"
```

Search:

```text
title
company
location
```

Use database indexes/full-text search if already available.

Do not download thousands of rows just to filter them in React.

---

# 25. APPLICATIONS MUST ALSO BE UNBOUNDED

The same principle applies to Applications.

Do NOT have:

```text
first 50
```

as a hidden permanent limit.

The database may contain:

```text
500
5,000
50,000
```

applications.

The UI should use pagination.

Example:

```text
Showing 1–100 of 527 applications
```

with:

```text
1 2 3 4 5 Next
```

---

# 26. APPLICATION DEFAULT SORT

Applications should default to:

```text
updated_at DESC
```

or the most useful existing application timestamp.

If the user has:

```text
APPLIED
INTERVIEW
OFFER
```

recently updated applications should appear first.

Do not sort applications by job discovery score unless there is a specific UI requirement.

---

# 27. DOCUMENTS SHOULD ALSO BE PAGINATED

Apply the same principle to Documents if the current Documents API has a hard limit.

Do not make a permanent:

```text
LIMIT 100
```

without pagination.

Use:

```text
Showing 1–100 of 2,341 documents
```

---

# 28. API DESIGN

Do NOT create a new API architecture.

Extend the existing endpoints.

For Jobs, prefer:

```http
GET /api/v1/jobs?page=1&page_size=100&sort=match_score_desc
```

Response:

```json
{
  "items": [],
  "page": 1,
  "page_size": 100,
  "total": 8742,
  "total_pages": 88
}
```

Adapt to the project's current API response conventions.

If the API already uses:

```text
limit
offset
```

you may preserve compatibility:

```http
GET /api/v1/jobs?limit=100&offset=0&sort=match_score_desc
```

but still return total metadata.

Do NOT break existing API clients unnecessarily.

---

# 29. APPLICATION API

Equivalent:

```http
GET /api/v1/applications?page=1&page_size=100
```

or the existing pagination convention.

Response must contain:

```text
items
total
page
page_size
total_pages
```

---

# 30. IMPORTANT: CHECK EVERY 100 LIMIT

Search the complete repository for:

```text
100
limit=100
LIMIT 100
page_size=100
DEFAULT_LIMIT
MAX_LIMIT
MAX_RESULTS
```

For every occurrence determine whether it is:

```text
GOOD:
batch size
API safety limit
UI page size

BAD:
global discovery limit
hidden database result truncation
permanent result cap
```

Fix all BAD cases.

Do not blindly replace every `100`.

---

# 31. DISCOVERY SHOULD CONTINUE BETWEEN RUNS

If the source has more results than:

```text
MAX_PAGES_PER_RUN
```

do not discard them.

Persist the continuation state where supported.

Example:

```text
Run 1:
pages 1–50

Run 2:
pages 51–100
```

If the source does not support persistent continuation, repeat the search safely and rely on deduplication.

Do not assume the next run will always return identical ordering.

---

# 32. SCHEDULER

Inspect the current scheduler/automation system.

If a scheduler already exists:

reuse it.

Do NOT create another cron architecture.

Desired behavior:

```text
Scheduled run
    ↓
discover jobs
    ↓
process batches
    ↓
```
