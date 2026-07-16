# 012 - Schedules list loading indicator

## Metadata

```yaml
status: done
priority: medium
type: feature
```

## Title

Show a loading indicator on the "Agendamentos" screen while schedules are being fetched

## Specification

The "Agendamentos" (schedules) list screen must show a visible loading
indicator (spinner icon) while the initial list of schedules has not yet
arrived from the backend, instead of silently rendering the "Nenhum
agendamento cadastrado" (no schedules) empty state.

### Context

`node-red/templates/agendamentos.html` (mirrored verbatim into
`node-red/flows.json`, node id `25072c26.808454`, `format` field) initializes
`scope.schedules = scope.schedules || []` and only replaces it once a
websocket message with an array payload arrives via `scope.$watch("msg", ...)`
(around line 923-951). Because the initial state is an empty array, the
`ir-empty` block (`ng-if="!editing_state.editing && schedules.length === 0"`,
line ~823) renders immediately and shows "Nenhum agendamento cadastrado" even
though data simply hasn't loaded yet. This is misleading: a user opening the
page briefly sees "you have no schedules" before the real list pops in.

There is currently no `isLoading`/`schedules_loaded` flag distinguishing "not
loaded yet" from "loaded and genuinely empty." Other loading states already
exist in this file (`editing_state.submitting`, `editing_state.enabled_submitting`,
`manual_pending[schedule.id]`), rendered via the `.ir-feedback.is-loading` CSS
class and button text swaps — but none of them cover the initial list load.

### Scope

#### In scope

- Add a `scope.schedules_loaded` (or equivalently named) boolean flag,
  initialized to `false`, set to `true` the first time a schedules array
  payload is received in the `scope.$watch("msg", ...)` handler.
- Render a loading indicator (spinner icon, consistent with the existing
  inline-SVG icon style used elsewhere in the template — no external icon
  library is used in this project) in place of the table/empty-state block
  while `!schedules_loaded`.
- Ensure the existing "Nenhum agendamento cadastrado" empty state only shows
  once `schedules_loaded` is `true` and the list is actually empty.
- Keep `node-red/templates/agendamentos.html` and the `format` field of node
  `25072c26.808454` in `node-red/flows.json` byte-identical after the change
  (this project keeps them in sync manually; verify with a diff/length check).

#### Out of scope

- Loading states for actions other than the initial list fetch (create,
  edit, delete, enable/disable, manual on/off) — those already exist.
- Changes to `novo-agendamento.html` or `historico.html`.
- Any backend/Node-RED flow wiring changes; `scope.schedules` continues to be
  populated the same way via the existing websocket `msg` watch.

## Impact analysis

### Files to inspect

- `node-red/templates/agendamentos.html` — current markup, styles, and
  AngularJS controller logic for the schedules screen.
- `node-red/flows.json` (node id `25072c26.808454`) — must mirror the
  template file exactly after the change.
- `tests/test_node_red_flow.py` — existing pattern for asserting on template
  content pulled from `flows.json`.
- `tasks/done/008-manual-action-loading-state.md` — closest prior art for
  adding a loading indicator to this dashboard.

### Files to change

- `node-red/templates/agendamentos.html` — add the loading flag, spinner
  markup/CSS, and gate the empty-state / table rendering on it.
- `node-red/flows.json` — apply the identical change to the `format` field of
  node `25072c26.808454`.

### Files to create

- None.

### Dependencies and integration points

- AngularJS scope/watch mechanism inside the Node-RED Dashboard
  `ui_template` widget; no HTTP/fetch calls are involved, data arrives via
  the existing websocket `msg` channel.

## Technical approach

### Design principles

- Keep each class and function focused on one responsibility.
- Depend on abstractions at architectural boundaries.
- Keep domain rules independent from infrastructure details.
- Prefer small, explicit interfaces and simple data flows.
- Avoid speculative abstractions, duplicated logic, and unrelated changes.

### Proposed changes

1. In the `<script>` block (around line 898), add
   `scope.schedules_loaded = scope.schedules_loaded || false;`.
2. In the `scope.$watch("msg", ...)` handler, right after
   `scope.schedules = msg.payload;` (line 945), set
   `scope.schedules_loaded = true;`.
3. Add a small spinner element (inline SVG or CSS-animated circle, matching
   the existing icon style — stroke-based, `currentColor`) with a new CSS
   class (e.g. `.ir-loading-spinner`) and rotation keyframe animation, styled
   with the project's existing color variables (`--ir-green`, `--ir-muted`).
4. Insert `<div class="ir-empty" ng-if="!schedules_loaded">...spinner +
   "Carregando agendamentos..." text...</div>` before the existing table
   block, and add `schedules_loaded` to the `ng-if` guards of the table
   block (`ng-if="!editing_state.editing && schedules_loaded && schedules.length > 0"`)
   and the "no schedules" empty state (`ng-if="!editing_state.editing &&
   schedules_loaded && schedules.length === 0"`).
5. Copy the finished template content into the `format` field of node
   `25072c26.808454` in `node-red/flows.json`, keeping both files identical.

### Performance considerations

- Expected complexity: `O(1)` — a single boolean flag check per render;
  no additional data processing or requests.
- Performance risks: none; this only affects conditional rendering.
- Mitigation: not applicable.

### Error handling and edge cases

- If a `schedule_error` message arrives before any schedules payload has
  been received, `schedules_loaded` stays `false` and the spinner remains
  visible alongside the error banner; this is acceptable since the existing
  `ir-feedback is-error` block is independent of the list rendering, but
  verify the spinner does not visually stack awkwardly with the error
  banner.
- Reconnection/re-render: since `scope.schedules_loaded` is only ever set to
  `true` (never reset to `false` after the first load), navigating back to
  the tab within the same session must not show the spinner again unless the
  Angular scope is actually reinitialized. Confirm this matches current
  Node-RED dashboard tab-switch behavior for other stateful scope fields
  (e.g. `scope.schedules`).

## Test specification

### Unit tests

- [ ] N/A (no JS unit test framework in this project; covered by the
      string-assertion test below).

### Integration tests

- [ ] `tests/test_node_red_flow.py`: add a test (e.g.
      `test_schedule_list_shows_loading_indicator_before_data_arrives`) that
      loads `node_id 25072c26.808454`'s `format` field from `flows.json` and
      asserts:
      - `"scope.schedules_loaded = scope.schedules_loaded || false"` is present.
      - `"scope.schedules_loaded = true"` is present inside the `$watch`
        handler.
      - the loading spinner markup (`ng-if="!schedules_loaded"`) is present.
      - the table and "no schedules" empty-state blocks now also require
        `schedules_loaded` in their `ng-if` guards.

### Regression tests

- [ ] Re-run `tests/test_node_red_flow.py::test_schedule_mobile_menu_opens_sidebar`
      and the other existing schedule-template tests to confirm unrelated
      markup/logic was not broken.
- [ ] Verify `node-red/templates/agendamentos.html` and the `format` field of
      node `25072c26.808454` in `node-red/flows.json` remain byte-identical.

### Test data and fixtures

- Uses the existing `node-red/flows.json` fixture loading pattern already
  present in `tests/test_node_red_flow.py` (`load_nodes()`).

## Acceptance criteria

The task is complete when:

- [ ] The requested behavior is implemented.
- [ ] Existing behavior remains unchanged outside the defined scope.
- [ ] New and changed behavior is covered by specs.
- [ ] Error cases and relevant edge cases are covered.
- [ ] The implementation follows the project's architecture and SOLID principles.
- [ ] The implementation is simple, readable, maintainable, and performant for the expected workload.
- [ ] Formatting, linting, type checks, and the full test suite pass.
- [ ] Documentation or user-facing examples are updated when needed.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if needed.
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- `node-red/templates/agendamentos.html` and the `format` field of node
  `25072c26.808454` in `node-red/flows.json` were confirmed byte-identical
  (50278 chars each) at the time this task was written; any edit must be
  applied to both to keep them in sync.
