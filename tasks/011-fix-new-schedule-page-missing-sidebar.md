# 011 - Fix new schedule page missing sidebar

## Metadata

```yaml
status: backlog
priority: medium
type: bug
```

## Title

Fix "Novo agendamento" page missing the sidebar menu

## Specification

The "Novo agendamento" (new schedule) page must keep the same top bar and
sidebar navigation shell used by the other dashboard pages ("Agendamentos"
and "Histórico"), so navigating into it does not feel like leaving the app.

### Context

`node-red/templates/novo-agendamento.html` only renders a small breadcrumb
bar (`.ir-create-topbar` with a "‹ Agendamentos / Novo agendamento" trail)
and drops straight into the form. It never renders the `.ir-topbar` +
`.ir-sidebar` shell that `agendamentos.html` and `historico.html` render, so
when a user opens "Novo agendamento" the left navigation menu and top bar
disappear, and reappear again once they navigate to "Histórico" or back to
"Agendamentos". This is inconsistent and disorienting.

### Scope

#### In scope

- Wrap the existing "Novo agendamento" form content with the same
  `.ir-topbar` / `.ir-layout` / `.ir-sidebar` / `.ir-content` shell markup
  used by the other two pages, with the "Novo agendamento" nav item marked
  active.
- Reuse the sidebar's mobile menu behavior (`toggleMobileMenu`,
  `closeMobileMenu`, `mobile_menu_open`, `.ir-mobile-backdrop`,
  `.ir-menu-button`) as already implemented in
  `node-red/templates/agendamentos.html`, so mobile behavior is consistent
  across all three pages.
- Keep the existing breadcrumb-style "Cancelar" / back-to-Agendamentos
  interaction available (it can live inside the new shell, e.g. as part of
  the page heading), since the current UX offers a quick way back.

#### Out of scope

- Changing the schedule creation form fields, validation, or submission
  logic.
- Fixing the same mobile menu gap on `historico.html` if found (note it as a
  follow-up only, do not fix in this task unless trivial).
- Any backend/Node-RED flow changes; this is template/markup only.

## Impact analysis

### Files to inspect

- `node-red/templates/novo-agendamento.html` — current page missing the
  shell; entire file needs restructuring around the existing form.
- `node-red/templates/agendamentos.html` — reference implementation of the
  topbar/sidebar shell including the mobile menu fix (most recently
  updated, commit "fix mobile menu").
- `node-red/templates/historico.html` — second reference implementation of
  the shell (older, without the mobile menu fix); useful to confirm the nav
  item list and active-state pattern.

### Files to change

- `node-red/templates/novo-agendamento.html` — add `.ir-topbar`,
  `.ir-layout`, `.ir-sidebar` (with nav links to `#!/0`, `#!/1`, `#!/2` and
  "Novo agendamento" marked `is-active`), `.ir-mobile-backdrop`, and wrap
  the current form inside `.ir-content` inside `main`. Port the
  `toggleMobileMenu`/`closeMobileMenu`/`mobile_menu_open` scope functions
  and related CSS from `agendamentos.html`.

### Files to create

- None.

### Dependencies and integration points

- Node-RED dashboard `ui_template` nodes render these HTML files as tabs
  (`#!/0`, `#!/1`, `#!/2`); navigation between tabs relies on
  `navigateToTab(index, event)`, which sets `window.location.hash` and
  reloads. The shell markup and its associated CSS/JS must be duplicated
  per template (no shared partial/include mechanism currently exists), so
  changes must mirror the pattern already used in the other two files
  exactly to avoid visual drift.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. Copy the `.ir-topbar` / `.ir-layout` / `.ir-sidebar` / mobile-menu CSS
   block from `agendamentos.html` into `novo-agendamento.html`'s `<style>`,
   renaming/removing any rules that would collide with the existing
   `.ir-create-*` classes still needed for the form styling.
2. Restructure the body: `<section class="ir-shell">` containing the
   `<header class="ir-topbar">` (brand + mobile menu button + system
   status), `<div class="ir-layout">` containing the mobile backdrop, the
   `<aside class="ir-sidebar">` with the three nav links ("Novo
   agendamento" as `is-active`), and `<main class="ir-content">` wrapping
   the existing eyebrow/title/subtitle/form markup (the `.ir-create-shell`
   inner content, minus its own breadcrumb topbar which becomes redundant
   once the sidebar nav is present, or is kept as a small in-page back
   link).
3. Port `scope.mobile_menu_open`, `scope.toggleMobileMenu`,
   `scope.closeMobileMenu` from `agendamentos.html` into the `<script>`
   block, alongside the existing `navigateToTab` and form logic.
4. Visually diff against `agendamentos.html` and `historico.html` to confirm
   spacing, active states, and responsive behavior match.

### Performance considerations

- Expected complexity: `O(1)` — static markup/CSS change, no algorithmic
  work.
- Performance risks: none; this is a template rendering change only.
- Mitigation: n/a.

### Error handling and edge cases

- Sidebar must render correctly even when `valves` is empty (existing
  `ir-empty-valves` case) — the shell wraps around the form and must not
  interfere with existing `ng-if` bindings.
- Mobile viewport: verify the hamburger menu opens/closes the sidebar and
  the backdrop dismisses it, matching `agendamentos.html` behavior.

## Test specification

### Unit tests

- [ ] None applicable (Node-RED dashboard templates have no unit test
      harness in this repo).

### Integration tests

- [ ] None applicable.

### Regression tests

- [ ] None applicable.

### Test data and fixtures

- Manual verification only, via the Node-RED dashboard in a browser.

## Acceptance criteria

The task is complete when:

- [ ] Opening "Novo agendamento" shows the same top bar and sidebar menu as
      "Agendamentos" and "Histórico", with "Novo agendamento" highlighted
      as the active nav item.
- [ ] Navigating between all three tabs no longer causes the sidebar to
      appear/disappear.
- [ ] The mobile hamburger menu works the same way on "Novo agendamento" as
      it does on "Agendamentos".
- [ ] The schedule creation form still works exactly as before (fields,
      validation, quick-time/duration chips, valve selection, weekday
      selection, submit, error/loading feedback).
- [ ] Existing behavior remains unchanged outside the defined scope.
- [ ] Manually verified in a browser (desktop and mobile widths) since this
      is a UI-only change with no automated test coverage.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if
      needed.
- [ ] Implement the smallest coherent change.
- [ ] Run focused checks (manual browser verification).
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation
      pass.

## Notes

- `historico.html` does not yet have the mobile menu fix that
  `agendamentos.html` received (see commit "fix mobile menu"); this task
  should mirror the more complete `agendamentos.html` pattern rather than
  the older `historico.html` one, since they are the newer reference.
- Consider a follow-up task to extract the shared shell (topbar + sidebar +
  mobile menu CSS/JS) into a single reusable snippet to avoid this class of
  drift recurring across the three templates.
