# Site Adapters

Each adapter implements the common browser contract.

Recommended adapters:
- workable
- greenhouse
- lever
- ashby
- smartrecruiters
- generic

A site adapter must never contain candidate-specific information.

Candidate data comes from the profile service.
Job data comes from the database.
Documents come from artifact storage.

This separation makes the browser layer reusable.
