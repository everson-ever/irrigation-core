---
status: backlog
priority: high
type: maintenance
---

## Title

Add TLS termination and secure dashboard cookies

## Specification

Document and deploy an HTTPS termination path for the Raspberry Pi installation.
Set the session cookie `Secure` attribute whenever the dashboard is served over
HTTPS, handle trusted proxy headers explicitly, and test both HTTP development and
HTTPS production configurations.

