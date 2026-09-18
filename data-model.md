# Data Model

Core tables:

profiles
jobs
job_matches
job_requirements
documents
applications
application_questions
application_answers
automation_runs
site_adapters
pipeline_events
dead_letter_events

Important unique constraints:

jobs(source, source_job_id)

applications(application_fingerprint)

documents(job_id, type, language, version)

application_answers(application_id, question_id)

All timestamps UTC.

## Job fingerprint

sha256(
  lower(trim(company))
  + "|"
  + lower(trim(title))
  + "|"
  + canonicalize(application_url)
)

## Application fingerprint

sha256(
  candidate_id
  + "|"
  + job_fingerprint
)

The same logical job must never enter the application pipeline twice.
