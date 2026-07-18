# 021 - Default history page to today with pagination

## Metadata

```yaml
status: backlog
priority: medium
type: feature
```

## Title

Default the history page to today's records and paginate results (15 per page)

## Specification

When the user opens the "Histórico" tab, the page must automatically load and
display today's irrigation records, without requiring the user to click
"Hoje" first. The results table must also be paginated, showing 15 records
per page, with controls to navigate between pages.

### Context

Today, `node-red/templates/historico.html` starts with `history_records`
empty (`scope.history_records = scope.history_records || []`) and only
triggers a search when the user clicks "Hoje" (`filterToday()`) or
"Pesquisar" (`filterRange()`). There is no automatic search on tab entry, so
the user always lands on an empty state first. There is also no pagination:
`visibleHistory()` renders every record returned by the backend in a single
table, which will get slow and hard to scan as history grows.

### Scope

#### In scope

- Trigger a "today" history search automatically when the Histórico tab/template is loaded (first render), reusing the existing `filterToday()` / `historyDay()` request (`action: "day"`) so the backend contract (`HistoryService.search_day`, the `irrigation history` CLI command, and the exec/file flow nodes) stays unchanged.
- Reflect the "today" state in the existing filter inputs (`start_date`, `end_date`) and `filter_description` so the UI is consistent with what is displayed.
- Add client-side pagination to the results table: 15 records per page, with page navigation controls (previous/next and/or page numbers) and a visible current page / total pages indicator.
- Reset pagination to page 1 whenever the record set changes (new search) or the search box (`history_query`) filters the visible rows.
- Keep the existing search-box filtering (`history_query`) working together with pagination (filtering operates on the full result set, pagination operates on the filtered set).

#### Out of scope

- Server-side pagination or changes to `HistoryService`, the SQLite repository, or the `irrigation history` CLI command — the backend already returns full result sets for a date range, which is small enough for client-side paging.
- Changing the default date range behavior of `filterRange()` (explicit "Pesquisar" with custom dates).
- Redesigning the stats cards, filters, or table columns.

## Impact analysis

### Files to inspect

- `node-red/templates/historico.html` — current filter/search wiring, `$watch("msg", ...)` handler, `visibleHistory()`, and the `<script>` scope functions that must be extended.
- `src/irrigation/application/services.py` (`HistoryService.search_day` / `search_range`, around lines 333-420) — confirm the "day" action contract used by `filterToday()` is unchanged.
- `src/irrigation/cli.py` (`_history_command`, lines 142-151) — confirm the CLI action names (`day`, `range`) consumed by the exec node.
- `node-red/flows.json` — nodes `dad8cd89.f8f81` (ui_template "Histórico"), `ef1f5bb.cb3c4a8` ("Formata pesquisa histórico"), `9ee06733.0ccea8` (exec "Pesquisar histórico"), `86f3f135.5c101` ("Formata records cadastrados") and `dbd8eebe.dbaa` (file node) — understand how a `send()` payload from the template reaches the backend and how results flow back into `msg.payload`, to confirm no flow changes are needed to trigger the initial search from the template itself.
- `scripts/sync_flows_templates.py` — confirms how `historico.html` is synced into `flows.json`, since the template is the single source of truth and must be re-synced after edits.

### Files to change

- `node-red/templates/historico.html` — add an on-load trigger that calls the equivalent of `filterToday()` once when the template scope initializes (guarding against re-triggering on every `$watch` cycle), and add pagination state/controls (`history_page`, `history_page_size = 15`, computed total pages, paged slice of `visibleHistory()`, and page navigation buttons/markup with matching CSS).
- `node-red/flows.json` — regenerate the `dad8cd89.f8f81` template node content via the sync script after `historico.html` changes (do not hand-edit the embedded HTML).

### Files to create

- None expected; this is a UI-only change to an existing template.

### Dependencies and integration points

- Node-RED `ui_template` scope lifecycle (Angular `scope.$watch`, `scope.send`) — the on-load trigger must run once when the dashboard tab/template is instantiated, not on every `msg` update, to avoid resending the search request repeatedly.
- Existing message contract between the template and the backend flow: `{ action: "day" }` for today and `{ action: "range", start_date, end_date }` for explicit range searches — must remain unchanged so `Formata pesquisa histórico` and the `irrigation history` exec command keep working.
- `scripts/sync_flows_templates.py`, which keeps `node-red/templates/*.html` and their embedded copies in `node-red/flows.json` in sync; must be run after editing the template.

## Technical approach

### Design principles

- Keep the change confined to the presentation layer (template scope), since the backend already supports day-range search and returns full result sets.
- Reuse the existing `filterToday()` request path instead of introducing a new action/message type.
- Keep pagination as a pure, derived computation (`page * pageSize` slicing) over `visibleHistory()`, with no duplicated state to keep in sync.
- Avoid speculative abstractions: no generic pagination directive/component is needed for a single table.

### Proposed changes

1. In `historico.html`'s script block, add a one-time initialization (e.g. an IIFE guard flag on `scope`, or Node-RED's template `onInit`/first-render hook) that calls the same logic as `filterToday()` so the page shows today's records immediately on load, and sets `filter_description` accordingly.
2. Add pagination state (`scope.history_page`, `scope.history_page_size = 15`) and a `scope.pagedHistory()` function that slices `visibleHistory()` by the current page; update the table's `ng-repeat` to iterate over `pagedHistory()` instead of `visibleHistory()`.
3. Add a `scope.totalPages()` helper and pagination controls in the markup (previous/next buttons and current/total page indicator), disabling navigation at the first/last page, and reset `scope.history_page = 1` whenever `history_records` or `history_query` changes.
4. Run `scripts/sync_flows_templates.py` to propagate the template changes into `node-red/flows.json`.

### Performance considerations

- Expected complexity: `O(n)` per render for filtering/slicing where `n` is the number of records for the selected date range (typically small — a single day's worth of irrigation events).
- Performance risks: none significant; pagination is purely client-side over an already-small in-memory array.
- Mitigation: not needed given expected data volume; revisit only if date ranges routinely return thousands of records.

### Error handling and edge cases

- No records for today: the existing empty state (`ir-empty`) must still show correctly after the automatic load.
- Fewer than 15 records: pagination controls should be hidden or disabled (single page).
- Switching the search query so the filtered set shrinks below the current page number: must clamp/reset to a valid page instead of showing a blank page.
- Backend/system offline on load: the automatic "today" request should behave the same as a manual click today (no special-cased error handling beyond what already exists for `send()`).

## Test specification

<!-- This project's automated tests are Python (pytest) and this change is confined to the Node-RED Angular template, which has no existing test harness. Verify manually via the Node-RED dashboard. -->

### Unit tests

- [ ] Not applicable (no JS test harness for `ui_template` scope code in this repo).

### Integration tests

- [ ] Not applicable — validate manually per the manual test plan below.

### Regression tests

- [ ] Run the existing Python suite (`pytest`) to confirm `HistoryService.search_day`/`search_range` and the CLI history command remain unaffected.

### Test data and fixtures

- Use existing seeded/manual irrigation runs (manual or scheduled) to populate `data/irrigation.db` with at least one record for today and several for other days, to validate the default filter and pagination boundaries (0, <15, exactly 15, >15 records).

## Acceptance criteria

The task is complete when:

- [ ] Opening the Histórico tab immediately shows today's records without any user interaction.
- [ ] The filter inputs and results toolbar reflect the "today" filter state on load.
- [ ] The results table shows at most 15 records per page, with working previous/next (or page-number) navigation.
- [ ] Pagination resets to page 1 on every new search and whenever the search box filters the record set.
- [ ] Explicit "Hoje" and "Pesquisar" (date range) actions continue to work as before.
- [ ] `node-red/flows.json` is regenerated via `scripts/sync_flows_templates.py` and stays in sync with `historico.html`.
- [ ] `pytest` passes.
- [ ] Manual verification in the Node-RED dashboard confirms the golden path (today's data on load, pagination) and edge cases (empty day, exactly 15 records, >15 records, query filtering interacting with pagination).

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if needed.
- [ ] Implement the smallest coherent change.
- [ ] Run `scripts/sync_flows_templates.py` after editing `historico.html`.
- [ ] Run focused checks (`pytest`).
- [ ] Manually verify in the running Node-RED dashboard.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `done` only after implementation and validation pass.

## Notes

- The backend already supports day-range search (`HistoryService.search_day`), so no Python/CLI changes are anticipated — this should be achievable entirely within `historico.html`.
- Pagination is implemented client-side because history search results are already bounded by date range and expected to be small; revisit only if this assumption changes.
