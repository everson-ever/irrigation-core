---
status: backlog
priority: high
type: performance
---

## Title

Add history retention and indexed active-interval lookups

## Specification

Define and enforce a history retention policy, add the indexes required by date and
active-interval queries, and replace controller-loop `list_all()` scans in
`has_active_manual` and `has_active_automatic` with bounded SQL queries. Verify query
plans and preserve service behavior with regression tests.

