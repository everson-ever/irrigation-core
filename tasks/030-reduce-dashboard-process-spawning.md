---
status: backlog
priority: medium
type: performance
---

## Title

Reduce per-action dashboard process spawning

## Specification

Measure CLI spawn latency and SD-card/database overhead on the Raspberry Pi, then
evaluate a longer-lived, least-privilege worker with a structured local IPC
contract. Preserve the stdin CLI fallback and JSON response contract; only adopt a
worker when measurements justify the added lifecycle and failure-handling complexity.

