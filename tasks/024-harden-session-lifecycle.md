---
status: backlog
priority: high
type: maintenance
---

## Title

Add server-side expiry, eviction, and rotation to dashboard sessions

## Specification

Replace the unbounded in-memory session `Set` in `node-red/settings.js` with a
store that enforces server-side expiry matching the cookie lifetime, removes
expired entries, and rotates tokens after authentication-sensitive events.
Add tests for expiry, logout, eviction, and token rotation.

