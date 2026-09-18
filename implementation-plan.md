# Implementation Plan

## Phase 0 — infrastructure
- Docker Compose
- PostgreSQL
- Redis
- MinIO
- API
- orchestrator
- shared contracts

## Phase 1 — profile
- parse master CV
- load website content
- create canonical profile
- manual profile editor

## Phase 2 — discovery
- Workable public connector
- normalized job model
- deduplication
- incremental discovery
- connector interface

## Phase 3 — matching
- deterministic requirement extraction
- semantic similarity
- LLM explanation
- configurable weighted score
- threshold

## Phase 4 — documents
- job-specific CV
- language detection
- cover letter
- artifact storage

## Phase 5 — application analysis
- public application schema where available
- browser inspection
- question classification

## Phase 6 — browser
- generic Playwright engine
- Workable adapter
- selector strategies
- persistent profiles
- traces/screenshots

## Phase 7 — automation
- event-driven pipeline
- retries
- duplicate prevention
- rate limits
- scheduled operation

## Phase 8 — dashboard
- pipeline monitor
- job review
- application history
- settings

## Phase 9 — additional ATS
- Greenhouse
- Lever
- Ashby
- SmartRecruiters
- generic adapter

## Phase 10 — hardening
- load tests
- failure recovery
- browser regression suite
- observability
- backup/restore
