# Architecture

## Runtime

Docker Compose orchestrates the complete local stack.

```text
                    +----------------+
                    |    Frontend    |
                    +-------+--------+
                            |
                    +-------v--------+
                    |      API       |
                    +-------+--------+
                            |
              +-------------+-------------+
              |                           |
        +-----v-----+               +-----v-----+
        | PostgreSQL|               |   Redis    |
        +-----------+               +-----+-----+
                                         |
             +---------------------------+---------------------------+
             |             |             |             |             |
        discovery      matching      documents     analyzer      browser
             |             |             |             |             |
             +-------------+-------------+-------------+-------------+
                                   |
                              +----v----+
                              | MinIO   |
                              +---------+

                         +---------------+
                         | Orchestrator  |
                         +---------------+
```

## Communication

Redis Streams are the preferred event mechanism.

Example:
`job.discovered.v1`
`job.matched.v1`
`job.qualified.v1`
`documents.generated.v1`
`application.analyzed.v1`
`application.ready.v1`
`application.submitted.v1`

PostgreSQL remains the authoritative state store.

Redis is transport, not durable business state.

## Idempotency

Every command has:
- idempotency_key
- correlation_id

Workers use database constraints and state checks before mutating records.

## Browser abstraction

```text
BrowserAgent
  |
  +-- SiteAdapter
        +-- WorkableAdapter
        +-- GreenhouseAdapter
        +-- LeverAdapter
        +-- AshbyAdapter
        +-- GenericAdapter
```

The GenericAdapter uses semantic DOM inspection and configurable heuristics.

Adapters can expose:
- detect()
- discover_application()
- inspect_form()
- map_fields()
- fill()
- verify()
- submit()

The generic engine should prefer user-facing Playwright locators such as role, label, text and placeholder, with CSS/XPath only as fallback.
