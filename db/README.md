Use Alembic migrations.

Initial migration should create:
profiles
jobs
job_requirements
job_matches
documents
applications
application_questions
application_answers
automation_runs
site_adapters
pipeline_events
dead_letter_events

Add indexes for:
jobs(source, source_job_id)
jobs(application_fingerprint)
job_matches(overall_score)
applications(application_fingerprint)
applications(status)
pipeline_events(event_type, created_at)
