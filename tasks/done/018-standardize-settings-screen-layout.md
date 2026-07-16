```yaml
status: done
priority: medium
type: refactor
```

## Title

Standardize the "Configurações" screen layout and remove the unused default-duration form

## Specification

The "Configurações" (Settings) dashboard tab must be rebuilt to use the same
visual shell (topbar + collapsible sidebar navigation) already used by the
Agendamentos, Novo agendamento, and Histórico tabs, instead of its current
flat breadcrumb-style layout. As part of this restyle, the "Tempo padrão para
desligar" (default shutoff duration) editable field and its companion
read-only "Tempo atual" display must be removed from the UI entirely, since
this control is no longer used. The only remaining screen content ("Trocar
senha") must be re-themed to fit the standard settings-page look (card/section
style consistent with the rest of the app) while living inside the standard
sidebar shell.

### Context

`node-red/flows.json` defines four dashboard tabs. Three of them
(Agendamentos, Novo agendamento, Histórico) share one visual shell — topbar
with a hamburger button, a left `ir-sidebar` with nav links to all four tabs,
and an `ir-content` area — implemented via the `.ir-shell/.ir-topbar/
.ir-layout/.ir-sidebar/.ir-nav/.ir-content` CSS classes first defined in
`node-red/templates/agendamentos.html`. The "Configurações" tab never
received this treatment: it is assembled from three disconnected widgets
instead of one shell-based template:

1. `ui_group` "Editar tempo padrão" (id `98667ea6.f9c95`) → `ui_form` node
   "Tempo padrão para desligar" (id `96f7b3d7.32c99`) — lets the user submit
   a new default duration.
2. `ui_group` "Tempo atual" (id `f885d082.99431`) → `ui_template` node
   "Tempo atual" (id `f6c23874.7f2538`) — a read-only display of the current
   value, refreshed by a 3-unit repeating `inject` node (id `d0cffdef.54ded`).
3. `ui_group` "Segurança" (order 3) → `ui_template` node "Trocar senha",
   whose markup mirrors `node-red/templates/configuracoes.html` — this is the
   only part of the screen using a card-style layout, and even that layout
   (`.ir-settings-card`, `.ir-settings-nav`) is a bespoke one-off, not the
   shared shell used elsewhere.

The default-duration form (group 1) is confirmed no longer used from the UI
side. Its backend counterpart (`SettingsService.default_duration_minutes()` /
`update_default_duration()` in
`src/irrigation/application/services.py:346-368`) is still exercised as a
fallback by `ManualControlService._manual_duration_minutes()` (services.py:
544-546) when a manual turn-on request omits a duration — that backend
behavior and the `irrigation settings <value|show>` CLI command
(`src/irrigation/cli.py:103-110,187-188`) are out of scope and must not be
touched; only the dashboard widgets that let a user edit/view the value from
the browser are being removed.

### Scope

#### In scope

- Rebuild the "Configurações" tab's on-screen layout to reuse the same
  `.ir-shell/.ir-topbar/.ir-layout/.ir-sidebar/.ir-nav/.ir-content` structure
  as `agendamentos.html`, `novo-agendamento.html`, and `historico.html`,
  with the "Configurações" nav button marked `is-active`.
- Remove the "Tempo padrão para desligar" edit form and the "Tempo atual"
  read-only display from the dashboard, including their dedicated Node-RED
  wiring (form, function, exec, inject nodes) and their `ui_group`s.
- Re-theme the remaining "Trocar senha" section to fit inside the new shell's
  content area, following the same card/section conventions used by other
  screens' modals/panels (e.g. `.ir-field`, `.ir-primary-button`,
  `.ir-feedback`) instead of the bespoke `.ir-settings-*` classes.
- Update `node-red/templates/configuracoes.html` so it stays the accurate
  mirror of the corresponding `ui_template` node's `format` field, per the
  existing repo convention described in `docs/DEVELOPER_GUIDE.md` section 12.
- Update or extend `tests/test_node_red_flow.py` /
  `tests/test_node_red_settings.py` coverage affected by these changes.

#### Out of scope

- Any change to `SettingsService`, `ManualControlService`, the `settings`
  CLI subcommand, or the `settings` SQLite table.
- Any change to the manual turn-on modal's own duration input (already
  present in `agendamentos.html`) or its default value.
- Any change to the Agendamentos, Novo agendamento, or Histórico tabs beyond
  what's needed to keep their nav lists consistent (adding no new links,
  since Configurações is already listed there).

## Impact analysis

### Files to inspect

- `node-red/flows.json` — locate and confirm current node/group ids before
  editing (ids may shift slightly if the file has changed since this task
  was written): `7a5ad52a.079c2c` (Configurações tab), `98667ea6.f9c95` /
  `96f7b3d7.32c99` (edit form + group), `f885d082.99431` / `f6c23874.7f2538`
  (current-value display + group), `5e998328.9aa40c` (extractor function),
  `92612eb4.8c939` (exec: `irrigation settings <value>`), `d0cffdef.54ded`
  (repeating inject), `d19f016a.a6ac8` (exec: `irrigation settings show`),
  `a7ddf74d.7238a8` (format function), and the "Segurança" group/template
  node holding the password-change markup.
- `node-red/templates/agendamentos.html` — canonical shell markup/CSS/JS to
  copy the sidebar pattern from (`.ir-shell`, `.ir-topbar`, `.ir-sidebar`,
  `.ir-nav`, mobile menu behavior, `navigateToTab`/`toggleMobileMenu`/
  `closeMobileMenu` scope functions).
- `node-red/templates/configuracoes.html` — current mirror of the
  "Trocar senha" `ui_template`, to be replaced with the new full-shell markup.
- `docs/DEVELOPER_GUIDE.md` section 12 ("Node-RED dashboard") — documents the
  `flows.json`/`templates/*.html` mirroring convention that must be
  respected.
- `tests/test_node_red_flow.py` and `tests/test_node_red_settings.py` —
  existing assertions about tab order/labels and dashboard markup that must
  keep passing (e.g. `test_dashboard_menu_order_and_history_label`,
  `test_schedule_mobile_menu_opens_sidebar`).
- `src/irrigation/application/services.py:346-368,544-546` — confirms the
  backend default-duration fallback that must remain untouched.

### Files to change

- `node-red/flows.json` — remove the "Editar tempo padrão" and "Tempo atual"
  `ui_group`s and their nodes (`ui_form`, both `exec` nodes, both `function`
  nodes, the repeating `inject` node); replace the "Segurança" `ui_template`
  node's `format` field with the new shell-based markup (topbar, sidebar nav
  with "Configurações" active, re-themed password-change card).
- `node-red/templates/configuracoes.html` — replace with the new shell-based
  markup so it mirrors the updated `ui_template` `format` field exactly.

### Files to create

- None expected — the existing `configuracoes.html` file is reused.

### Dependencies and integration points

- Node-RED dashboard wiring only (`ui_tab` → `ui_group` → widget nodes);
  no HTTP API, domain, or CLI surface is touched.
- The password-change flow's existing wiring (`ui_action: "change_password"`
  message contract, `password_changed` / `password_change_error` topics)
  must be preserved unchanged — only its surrounding markup/CSS moves into
  the new shell.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. In `flows.json`, delete the two default-duration `ui_group`s and their six
   associated nodes (form, function ×2, exec ×2, inject), after confirming no
   other node references them as a wire target (already verified: none do).
2. Copy the shell CSS/markup/JS scaffolding from `agendamentos.html` into a
   new version of `configuracoes.html`, mark the "Configurações" nav button
   `is-active`, and drop the duration-related sections entirely.
3. Rebuild the "Trocar senha" section inside the new `ir-content` area using
   the app's standard field/button/feedback classes instead of the bespoke
   `.ir-settings-*` ones, preserving all existing `ng-model`/`ng-submit`/
   `scope.$watch` logic verbatim.
4. Paste the finished template into the "Segurança" `ui_template` node's
   `format` field in `flows.json`, keeping the file and the node byte-for-byte
   in sync as the repo convention requires.
5. Update/add assertions in `tests/test_node_red_flow.py` /
   `test_node_red_settings.py` covering: the removed nodes/groups are gone,
   the new shell markup is present on the Configurações template, and the
   password-change contract still works.

### Performance considerations

- Expected complexity: `O(1)` — static dashboard markup change, no runtime
  algorithmic work.
- Performance risks: none; removing a 3-unit repeating inject node slightly
  reduces idle dashboard load.
- Mitigation: not applicable.

### Error handling and edge cases

- Ensure removing the default-duration nodes doesn't leave dangling wire
  references elsewhere in `flows.json` (verified none exist as of writing).
- Ensure the mobile hamburger menu / sidebar toggle behaves identically to
  the other three tabs (open/close, backdrop click-to-close).
- Ensure the password-change success/error feedback and the post-change
  logout redirect keep working after the markup move.

## Test specification

### Unit tests

- [ ] None expected (no Python domain/application logic changes).

### Integration tests

- [ ] `tests/test_node_red_flow.py` — the removed node ids/groups are absent
      from `flows.json`.
- [ ] `tests/test_node_red_flow.py` — the Configurações template contains the
      standard shell markup (`ir-shell`, `ir-sidebar`, `ir-menu-button`,
      `toggleMobileMenu`, "Configurações" nav marked active) mirroring the
      pattern already asserted for the schedule template.
- [ ] `tests/test_node_red_settings.py` — updated to reflect the new
      template content where it previously asserted on the old
      `.ir-settings-*` layout.

### Regression tests

- [ ] `test_dashboard_menu_order_and_history_label` continues to pass
      unchanged (tab id/order/name untouched).
- [ ] `test_schedule_mobile_menu_opens_sidebar` continues to pass unchanged.

### Test data and fixtures

- No new fixtures; tests read `node-red/flows.json` directly as today.

## Acceptance criteria

The task is complete when:

- [ ] The Configurações screen visually matches the other three screens'
      topbar + sidebar shell, with its own nav button active.
- [ ] The "Tempo padrão para desligar" field and the "Tempo atual" display
      are fully removed from the dashboard (markup, wiring, and groups).
- [ ] The "Trocar senha" functionality behaves exactly as before, restyled
      to the standard settings look.
- [ ] `node-red/templates/configuracoes.html` and the corresponding
      `ui_template` node in `flows.json` are identical, per repo convention.
- [ ] Existing behavior remains unchanged outside the defined scope
      (backend `SettingsService`/CLI untouched).
- [ ] New and changed behavior is covered by specs.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] Documentation is updated if `docs/DEVELOPER_GUIDE.md` section 12
      references anything made stale by this change (e.g. mentions of the
      default-duration widgets, if any).

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if
      needed (node ids in `flows.json` may have shifted).
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `status: done` only after implementation and
      validation pass.

## Notes

- Node ids referenced above were captured by directly parsing
  `node-red/flows.json` while writing this task; re-verify them before
  editing, since Node-RED regenerates/reassigns ids on manual edits made
  through its editor UI.
- The default-duration backend capability is intentionally kept reachable
  only via the `irrigation settings <value|show>` CLI command going forward;
  this is a deliberate reduction of UI surface, not a bug.
