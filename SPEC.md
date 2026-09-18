# AI Job Agent — Full System Specification

## Goal

Build a production-oriented personal AI job application platform that continuously discovers jobs, evaluates compatibility, creates job-specific application documents, analyzes application forms and uses a flexible Playwright browser agent to complete applications across different job sites.

The system is designed for unattended operation after the user explicitly enables it.

## Core pipeline

DISCOVER
-> NORMALIZE
-> DEDUPLICATE
-> MATCH
-> QUALIFY
-> GENERATE_DOCUMENTS
-> ANALYZE_APPLICATION
-> PREPARE_APPLICATION
-> FILL_APPLICATION
-> SUBMIT
-> VERIFY
-> RECORD

Each stage must be independently executable and idempotent.

## Microservices

### 1 orchestrator
Responsibilities:
- scheduled execution
- event coordination
- retries
- locking
- pipeline state transitions
- dead-letter handling
- configurable thresholds

It must not contain business logic belonging to other services.

### 2 job-discovery
Initial source:
- public Workable jobs

Architecture must support additional connectors:
- greenhouse
- lever
- ashby
- smartrecruiters
- generic ATS/site adapter

Discovery output:
- normalized job
- source
- source_job_id
- company
- title
- URL
- location
- remote status
- description
- requirements
- publication metadata

### 3 job-matching
Input:
- normalized job
- canonical profile
- preferences

Output:
- score 0-100
- confidence
- component scores
- hard requirements
- matching skills
- missing skills
- explanation
- qualification status

Default threshold: 95.

Scoring must combine deterministic rules and semantic/LLM analysis.

Suggested weighting:
skills 30
experience 20
role 15
seniority 10
language 10
location 5
education 5
industry 3
employment 2

All weights configurable.

### 4 cv-generator
Input:
- profile
- job
- match

Output:
- German/English CV as appropriate
- optional cover letter

Never fabricate:
- employer
- dates
- degree
- certification
- language level
- years of experience
- professional technology experience

The master CV is immutable.

### 5 application-analyzer
Input:
- job
- application URL
- optional public application schema/API data

Output:
- form schema
- required fields
- optional fields
- screening questions
- file requirements
- confidence
- site adapter recommendation

### 6 browser-agent
Use Playwright.

The agent must be generic and adapter-driven.

Capabilities:
- persistent browser profile
- multiple browser engines where useful
- DOM/ARIA inspection
- label/role/text/placeholder locators
- iframe support
- file uploads
- dropdowns
- checkboxes
- radio groups
- multi-step forms
- screenshots
- traces
- failure recovery
- site adapters
- semantic field mapping

Never bypass CAPTCHA/MFA/anti-bot/security challenges.

### 7 API
Provides:
- jobs
- matches
- documents
- applications
- pipeline controls
- health
- metrics
- manual rerun endpoints

### 8 frontend
Dashboard:
- pipeline status
- job list
- score breakdown
- generated documents
- application queue
- automation logs
- settings

## Canonical profile

profile/profile.yaml is the editable source of truth.

Store:
- identity
- contact
- location
- work authorization
- education
- certifications
- languages
- employment history
- technical skills
- AI skills
- preferences

Distinguish:
FACT
INFERENCE
PREFERENCE

Never turn an inference into a fact automatically.

## Duplicate protection

Create a deterministic fingerprint:

hash(
normalized_company +
normalized_title +
canonical_application_url
)

Also maintain:
- source_job_id
- company + title similarity
- application URL canonicalization

Before an application can be submitted:
- reject if an application with the same fingerprint exists
- reject if a prior successful submission exists
- reject if status is SUBMITTED or VERIFIED

## Automation states

DISCOVERED
NORMALIZED
MATCHED
QUALIFIED
DOCUMENTS_READY
FORM_ANALYZED
READY_TO_APPLY
FILLING
SUBMITTING
SUBMITTED
VERIFIED
FAILED
BLOCKED
DUPLICATE

## Human/full-auto modes

DISCOVERY_ONLY
MATCH_ONLY
DOCUMENTS
PREPARE_APPLICATION
FULL_AUTO

Default:
PREPARE_APPLICATION

FULL_AUTO must be explicitly enabled.

## Safety

If a site requests:
- CAPTCHA
- MFA
- unusual authentication
- security challenge
- unexpected identity verification

set application to BLOCKED and stop that workflow.

Do not attempt to defeat security controls.

## Rate limiting

Per-site configurable:
- max applications/hour
- max applications/day
- delay range
- concurrent browser sessions

Do not hammer sites.

## Observability

Every service logs:
- correlation_id
- job_id
- application_id
- service
- event
- duration
- result
- error

Store screenshots/traces for browser failures.

## Testing

- unit tests
- contract tests
- integration tests
- browser tests against local mock forms
- connector tests with recorded fixtures

Never make a real submission in automated tests.
