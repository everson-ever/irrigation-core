# Show Loading Feedback While a Manual Valve Action Is In Progress

## Metadata

```yaml
status: backlog
priority: medium
type: feature
```

## Title

Show a loading state on `Ligar agora` / `Desligar agora` while the manual action request is in flight

## Specification

### Context

The schedules dashboard (`node-red/flows.json`, `Agendamentos` ui_template, node id `25072c26.808454`, `format` field around line 681) lets the user manually turn a section on (`Ligar agora`, via the confirmation modal's `confirmManualDuration()`) or off (`Desligar agora`, via `turnScheduleOff()`). Both send `{ ui_action: "manual", action: "on"|"off", id, valve_pin, ... }` to the `Roteia ações da tabela de agendamentos` function node (id `d4f14a77.92f3b1`, line 694), which immediately relays a `manual_feedback` message back to the same ui_template (same tick, before the command actually runs), and separately forwards the request to `Formata acionamento manual` (id `5b92c8ad.78d3e8`, line 374) and the `Irrigar manualmente` exec node (id `2a2ceafd.1bf566`, line 295), which runs `irrigation valve <pin>,<action>[,...]`.

Because `manual_feedback` arrives instantly, the row's status flips right after the click with no visual indication that a request is in progress, unlike the existing `Salvando...`/loading conventions already used for the create and edit schedule forms (task 007's predecessor, `004-improve-schedule-usability.md`, and `scope.editing_state.submitting` in the same template). This is inconsistent and can read as unresponsive or, if the click is accidentally repeated, as if nothing happened.

Note: `ManualControlService.turn_on` (`src/irrigation/application/services.py`, line 328) blocks the CLI process for the full requested duration when called with `wait=True` (the default used by this exec node, since `--no-wait` is only passed in tests) via `_wait_for_auto_turn_off` (line 374), which is what turns the valve back off automatically after the manual duration elapses. Because of this, the exec node's own completion cannot be used as the "action confirmed" signal for `Ligar agora` without either waiting the full duration (bad UX) or skipping `--no-wait`'s auto turn-off entirely (a functional regression). This task keeps that existing constraint and architecture unchanged; it only adds an explicit, bounded loading indication around the existing click-to-acknowledgment round trip, consistent with how the rest of the dashboard already provides loading feedback.

### Scope

#### In scope

- Show a visible loading state on the specific row's action button immediately after the user confirms `Ligar agora` (in the duration modal) or clicks `Desligar agora`.
- Disable that row's manual action button while its own action is pending, so the user cannot trigger a duplicate request for the same schedule while one is already in flight.
- Clear the loading state once the corresponding acknowledgment (`manual_feedback`) for that schedule id is received and the row status has been updated.
- Add a bounded client-side fallback so a row cannot stay stuck in a loading state indefinitely if no acknowledgment is ever received (e.g. a dropped dashboard message).

#### Out of scope

- Changing when or how `ManualControlService.turn_on`/`turn_off` are invoked, including the blocking wait-for-duration behavior and the `--no-wait` CLI flag.
- Making the loading indicator reflect true end-to-end hardware confirmation for `Ligar agora` (would require changing the CLI/service contract to decouple "valve turned on" from "wait for auto turn-off", which is a separate, larger change).
- Changing schedule create/edit loading behavior (already covered by `004-improve-schedule-usability.md`).
- Changing manual action validation rules, payload formats, or the `manual_feedback` message contract.
- Adding a global page-level loading overlay; the loading state is scoped to the affected row only.

## Impact analysis

### Files to inspect

- `node-red/flows.json` — the `Agendamentos` ui_template's `format` field (node id `25072c26.808454`, line 681): the row action buttons, `scope.openManualDuration`, `scope.confirmManualDuration`, `scope.turnScheduleOff`, `scope.applyManualFeedback`, and the `$watch("msg", ...)` handler that receives `manual_feedback`.
- `node-red/flows.json` — `Roteia ações da tabela de agendamentos` (id `d4f14a77.92f3b1`, line 694) to confirm exactly when and how `manual_feedback` is emitted relative to the exec call.
- `src/irrigation/application/services.py` — `ManualControlService.turn_on`/`turn_off` (lines 328-361) and `_wait_for_auto_turn_off` (line 374), to confirm the blocking behavior that limits what "loading until confirmed" can honestly mean for `Ligar agora`.
- `tasks/done/004-improve-schedule-usability.md` — existing precedent and conventions for loading states (`editing_state.submitting`, the `.ir-loading` CSS class) already used in this same template.

### Files to change

- `node-red/flows.json` — `Agendamentos` ui_template `format` field: add per-row pending state, update button markup/labels/disabled state, and clear the pending state from the `manual_feedback` handler plus a fallback timeout.

### Files to create

- None expected.

### Dependencies and integration points

- The `manual_feedback` message (topic `"manual_feedback"`, payload `{ id, action, valve_pin, duration_minutes }`) is the only existing signal the ui_template receives about a manual action; the loading state must key off the same schedule `id` used there.
- The dashboard already reuses `.ir-btn:disabled` styling and a "verb + ..." label convention (`editing_state.submitting ? "Salvando..." : "Salvar alterações"`) for in-progress actions; the new state should follow the same convention rather than introducing new UI elements.

## Technical approach

### Design principles

- Keep the change local to the existing ui_template client-side state; do not alter the Node-RED wiring, the `manual_feedback` contract, or backend service behavior.
- Reuse the existing loading/disabled-button convention already used for schedule create/edit instead of inventing a new pattern.
- Key the pending state by schedule id so only the row the user acted on shows loading, not the whole table.

### Proposed changes

1. Add `scope.manual_pending = scope.manual_pending || {};` (an object keyed by schedule id) to the ui_template's init block.
2. In `confirmManualDuration()`, set `scope.manual_pending[schedule.id] = "on"` before returning the send payload; in `turnScheduleOff()`, set `scope.manual_pending[schedule.id] = "off"` before returning its payload.
3. Update the `Ligar agora` / `Desligar agora` buttons to add `ng-disabled="manual_pending[schedule.id]"` and show a pending label (e.g. `"Ligando..."` / `"Desligando..."`) while `manual_pending[schedule.id]` matches that action, following the same ternary-label pattern already used for `editing_state.submitting`.
4. In `applyManualFeedback(payload)`, after applying the status update, clear `delete scope.manual_pending[payload.id];` so the row returns to its normal actionable state.
5. Add a bounded fallback timeout (e.g. `$timeout`-equivalent via the template's existing scope mechanism) started alongside each pending flag that clears `manual_pending[schedule.id]` for that id if no `manual_feedback` arrives within a fixed window (e.g. 15s), so a dropped message cannot leave the button disabled forever.

### Performance considerations

- Expected complexity: `O(1)` per click and per acknowledgment, keyed by schedule id.
- Performance risks: none meaningful; the pending map is small and bounded by the number of visible schedules.
- Mitigation: not applicable.

### Error handling and edge cases

- Clicking `Ligar agora`/`Desligar agora` again on a row that is already pending must be prevented by the disabled state.
- If the fallback timeout fires before a real acknowledgment, the row must return to its previous actionable state without leaving stale pending state behind; if the acknowledgment arrives afterward, applying it must not throw even though the pending flag was already cleared.
- Switching between rows must not affect another row's pending state; only the acted-on schedule id's button is disabled/labeled as loading.
- The pending state must be scoped per schedule id, not per action type globally, so acting on two different schedules concurrently shows independent loading states.

## Test specification

### Unit tests

- [ ] `confirmManualDuration()` sets the row's pending state to `"on"` before returning its payload.
- [ ] `turnScheduleOff()` sets the row's pending state to `"off"` before returning its payload.
- [ ] `applyManualFeedback()` clears the row's pending state after applying the status update.

### Integration tests

- [ ] Confirming `Ligar agora` in the duration modal disables that row's button and shows a loading label until `manual_feedback` for that schedule id is received.
- [ ] Clicking `Desligar agora` disables that row's button and shows a loading label until `manual_feedback` for that schedule id is received.
- [ ] Receiving `manual_feedback` for a schedule id re-enables that row's button and restores its normal label.
- [ ] A schedule whose acknowledgment never arrives has its loading state cleared automatically after the fallback timeout.

### Regression tests

- [ ] Other rows remain unaffected (not disabled, no loading label) while one row is pending.
- [ ] Existing schedule create/edit loading behavior is unchanged.
- [ ] Existing manual on/off behavior (status update, section labels, error banner) is unchanged outside of the added loading indicator.

### Test data and fixtures

- At least two visible schedules on different valves, to verify pending state isolation between rows.
- A simulated missing/delayed `manual_feedback` message to exercise the fallback timeout path.

## Acceptance criteria

The task is complete when:

- [ ] Confirming `Ligar agora` shows a loading state on that row's button until the action is acknowledged.
- [ ] Clicking `Desligar agora` shows a loading state on that row's button until the action is acknowledged.
- [ ] The affected row's action button is disabled while its own action is pending, preventing duplicate clicks.
- [ ] A row whose acknowledgment never arrives is not left disabled indefinitely.
- [ ] Other rows are unaffected by one row's pending state.
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

- The initial request is in Portuguese; this task is intentionally written in English as required by the task-generation convention.
- The loading indicator reflects the click-to-acknowledgment round trip already present in the flow (`manual_feedback` is emitted immediately by the routing function, before the underlying `irrigation valve` command necessarily finishes). It is not, and cannot honestly be without a larger backend change, a true end-to-end hardware confirmation for `Ligar agora`, because the CLI process only returns after the full manual duration elapses. If real hardware-confirmed feedback is wanted later, that would need a separate task to decouple "valve turned on" from "wait for auto turn-off" in `ManualControlService`.
