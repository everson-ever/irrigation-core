---
status: backlog
priority: critical
type: maintenance
---

## Title

Restrict Node-RED editor access and permissions

## Specification

Bind the Node-RED admin/editor endpoint to localhost or another explicitly trusted
management interface and review the current `permissions: "*"` grant. Keep the
dashboard reachable as intended while documenting the management access path and
testing that remote dashboard users cannot reach editor capabilities.

