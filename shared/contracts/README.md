Versioned event contracts live here.

Example event names:
- job.discovered.v1
- job.matched.v1
- job.qualified.v1
- documents.generated.v1
- application.analyzed.v1
- application.ready.v1
- application.submitted.v1
- application.failed.v1

Every event must include:
event_id
event_type
version
timestamp
correlation_id
entity_id
payload
