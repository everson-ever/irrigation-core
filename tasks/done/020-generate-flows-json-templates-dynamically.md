# 020 — Generate flows.json dashboard templates dynamically

## Metadata

```yaml
status: done
priority: medium
type: refactor
```

## Title

Populate `node-red/flows.json` `ui_template` HTML from `node-red/templates/*.html` dynamically

## Specification

`node-red/flows.json` embeds the full dashboard HTML for four `ui_template`
nodes directly inside their `format` field, and the exact same HTML also
exists as standalone files under `node-red/templates/`:

| `ui_template` node id | node name | template file |
|---|---|---|
| `25072c26.808454` | Agendamentos | `node-red/templates/agendamentos.html` |
| `dad8cd89.f8f81` | Histórico | `node-red/templates/historico.html` |
| `681694c2.ce0b1c` | Novo agendamento | `node-red/templates/novo-agendamento.html` |
| `d6f0b5a1.42c8e3` | Trocar senha | `node-red/templates/configuracoes.html` |

The two copies already drifted (e.g. `Agendamentos` format is 60992 bytes vs.
61099 bytes in `agendamentos.html`), which is exactly the failure mode this
task must eliminate: whoever edits the dashboard has to remember to update
both places, and nothing catches it when they forget.

Instead, `node-red/templates/*.html` must become the single source of truth.
A sync step reads each template file and injects its contents into the
matching node's `format` field in `node-red/flows.json`, and this step must
run automatically:

1. Every time the Docker container starts (`docker-compose.yml` /
   `Dockerfile` node-red service), so local/dev usage always serves the
   current templates.
2. Every time the standalone executable/deploy package is generated
   (`scripts/build-binary.sh`), so the zip shipped to the Raspberry Pi has an
   up-to-date `node-red/flows.json`.

### Context

The dashboard HTML is non-trivial (25–61 KB per page) and is edited directly
as `.html` files for syntax highlighting/tooling. `flows.json` is Node-RED's
own persistence format and is committed so it can be imported directly by the
Node-RED editor and shipped in deploy packages. Keeping both in sync by hand
does not scale and has already caused drift. `tests/test_node_red_flow.py`
asserts against the HTML embedded in `flows.json` directly, so whatever
mechanism is chosen must guarantee `flows.json` reflects the templates before
those tests (and the running dashboard) are ever exercised.

### Scope

#### In scope

- A script that reads `node-red/templates/*.html` and writes each file's
  contents into the corresponding `ui_template` node's `format` field in
  `node-red/flows.json`, leaving every other field/node untouched and
  preserving key order/formatting as much as reasonably possible (avoid
  noisy diffs).
- Wiring that script into container startup (dev `docker-compose`/Dockerfile
  flow) and into `scripts/build-binary.sh` (packaging flow), so both
  "container executed" and "executable generated" paths always produce a
  `flows.json` in sync with the templates.
- A regression check (test or script invocation in CI/test suite) that fails
  when `flows.json` is committed out of sync with `node-red/templates/`.
- Updating `docs/DEVELOPER_GUIDE.md` (and `deploy/package-readme.md` if
  relevant) to document the new source of truth and workflow for editing
  dashboard HTML.

#### Out of scope

- Rewriting the dashboard HTML/CSS/JS itself.
- Changing the Node-RED flow structure, node ids, or any node other than the
  four `ui_template` nodes listed above.
- Introducing a Node-RED build/plugin pipeline (e.g. webpack) — keep the sync
  mechanism a small, dependency-free script consistent with the rest of the
  tooling in `scripts/`.
- Templating engine features (includes, partials, variable interpolation)
  inside the HTML files — this task only removes duplication, not further
  changes the template format.

## Impact analysis

### Files to inspect

- `node-red/flows.json` — current committed artifact containing the
  duplicated `format` fields; understand full node structure before editing.
- `node-red/templates/*.html` — the four template files that must become the
  source of truth.
- `Dockerfile` — how the `node-red` image/environment is built and what runs
  at container start.
- `docker-compose.yml` — the `node-red` service `command`, which currently
  execs `node-red` directly (a plain arg list, not a shell), relevant to how
  a pre-start sync step gets invoked.
- `scripts/build-binary.sh` — packaging script that copies `node-red/` into
  the deploy zip; the sync must run before that copy (or before the zip step)
  so the packaged `flows.json` is current.
- `scripts/install-raspberry.sh` — confirms `flows.json` is imported as-is on
  the Pi, with no further processing, so it must be fully synced by the time
  it's packaged.
- `tests/test_node_red_flow.py` — existing tests assert directly on
  `flows.json`'s embedded `format` strings; must keep passing and should be
  extended to guard against drift.
- `docs/DEVELOPER_GUIDE.md` — describes the system for new contributors;
  needs a short section on this workflow.

### Files to change

- `docker-compose.yml` — make the `node-red` service run the sync script
  before starting `node-red` (e.g. wrap `command` in `sh -c` or add an
  entrypoint script).
- `Dockerfile` — add the sync entrypoint/script if the production image path
  also needs it (confirm whether the Pi install uses this image or only the
  compiled binary + raw `node-red/flows.json` from the zip).
- `scripts/build-binary.sh` — call the sync script before
  `cp -r "${PROJECT_DIR}/node-red" "${PACKAGE_DIR}/node-red"` (or immediately
  after, before the zip step).
- `tests/test_node_red_flow.py` — add a test that regenerates `flows.json`
  from the templates (in memory or to a temp file) and asserts it matches the
  committed one, so CI catches drift instead of relying on manual discipline.
- `docs/DEVELOPER_GUIDE.md` — document that `node-red/templates/*.html` is
  the source of truth and how/when `flows.json` gets regenerated.

### Files to create

- `scripts/sync-flows-templates.py` (or similar) — the sync script itself.
  Python fits the existing tooling better than adding a Node dependency at
  the repo root (there is no root `package.json`).

### Dependencies and integration points

- Node-RED editor: importing `node-red/flows.json` directly must still work
  unchanged — the sync only rewrites `format` strings, not node shape.
- `docker-compose.yml` node-red service `command` is currently a literal arg
  list (exec form), not a shell — switching to a shell wrapper needs care not
  to break signal handling for `node-red`.
- `scripts/build-binary.sh` is meant to run standalone on a Raspberry Pi (or
  matching architecture machine) with only `python3`/`pip`/`nuitka`
  available — the sync script must not require Node-RED or npm to run.

## Technical approach

### Design principles

- Keep the sync script a single, focused responsibility: read templates,
  write them into `flows.json`. No unrelated flow edits.
- Make the id→template-file mapping explicit and readable (a small dict),
  not inferred from node names (accents/naming drift make that fragile).
- Fail loudly (non-zero exit) if a mapped node id is missing from
  `flows.json` or a mapped template file is missing, so both startup and the
  build script abort instead of silently shipping stale HTML.
- Idempotent: running the script twice in a row produces no further diff.

### Proposed changes

1. Add `scripts/sync-flows-templates.py`: loads `node-red/flows.json`,
   applies an explicit `{node_id: template_filename}` mapping, replaces each
   node's `format` field with the matching file's contents, and writes the
   file back with the same JSON formatting style Node-RED itself uses
   (check current indentation/line endings in `flows.json` to match, since
   Node-RED re-writes this file too when the editor saves).
2. Wire it into `docker-compose.yml`'s `node-red` service (and `Dockerfile`
   if the production image needs the same behavior) so it runs once, before
   `node-red` starts.
3. Wire it into `scripts/build-binary.sh`, right before the `node-red`
   directory is copied into the deploy package directory.
4. Add a regression test (or extend `tests/test_node_red_flow.py`) that runs
   the sync logic against a copy of `flows.json` and asserts no diff against
   the committed file, catching future drift in CI.
5. Update `docs/DEVELOPER_GUIDE.md` with a short "Dashboard templates" note:
   edit `node-red/templates/*.html`, then run the sync script (or rely on
   `docker-compose up` / `build-binary.sh` doing it automatically) to update
   `flows.json`.

### Performance considerations

- Expected complexity: `O(n)` in the size of `flows.json` (single parse +
  rewrite, run at most once per container start / build).
- Performance risks: none meaningful — `flows.json` is ~190 KB, parsed once.
- Mitigation: not needed given the trivial data size.

### Error handling and edge cases

- Missing template file referenced by the mapping → abort with a clear error
  before container start / before packaging (don't fall back to stale data).
- Node id in the mapping no longer present in `flows.json` (e.g. after a
  manual Node-RED editor change) → abort with a clear error rather than
  silently skipping.
- `flows.json` re-saved by the Node-RED editor with different key ordering or
  whitespace → sync script must only touch the four `format` values, not
  reformat the rest of the file, to avoid unrelated diff noise.

## Test specification

### Unit tests

- [ ] Sync script correctly replaces the `format` field for each of the four
      mapped node ids and leaves all other nodes/fields byte-identical.
- [ ] Sync script raises/exits non-zero when a mapped template file is
      missing.
- [ ] Sync script raises/exits non-zero when a mapped node id is missing from
      `flows.json`.

### Integration tests

- [ ] Running the sync script against the current repo state produces zero
      diff (i.e., `node-red/flows.json` and `node-red/templates/*.html` are
      in sync after this task lands).

### Regression tests

- [ ] `tests/test_node_red_flow.py` continues to pass unchanged (its
      assertions read `flows.json`'s `format` fields, which must still
      contain the expected markers after sync).
- [ ] New test fails if someone edits a template file without re-running the
      sync (drift is caught automatically instead of relying on memory).

### Test data and fixtures

- Use the existing `node-red/flows.json` and `node-red/templates/*.html` as
  fixtures; no new test data needed.

## Acceptance criteria

The task is complete when:

- [ ] `node-red/templates/*.html` is the single source of truth for
      dashboard HTML; `flows.json`'s `format` fields are generated from it.
- [ ] The sync runs automatically when the Docker container starts.
- [ ] The sync runs automatically when the deploy package/executable is
      generated via `scripts/build-binary.sh`.
- [ ] A test/check fails CI if `flows.json` drifts from the templates.
- [ ] Existing behavior (dashboard rendering, Node-RED import,
      `tests/test_node_red_flow.py`) remains unchanged outside this scope.
- [ ] `docs/DEVELOPER_GUIDE.md` documents the new workflow.
- [ ] Formatting, linting, type checks, and the full test suite pass.

## Implementation checklist

- [ ] Confirm the task number and filename.
- [ ] Inspect all files listed in the impact analysis.
- [ ] Reassess the affected files before coding and update this task if
      needed.
- [ ] Implement the smallest coherent change.
- [ ] Add or update specs.
- [ ] Run focused checks.
- [ ] Run the full validation suite.
- [ ] Validate the implementation against every acceptance criterion.
- [ ] Move the issue to `status: done` only after implementation and
      validation pass.

## Notes

- Current drift observed while writing this task (bytes in `flows.json`
  `format` vs. matching `.html` file): Agendamentos 60992 vs 61099,
  Histórico 25329 vs 25369, Novo agendamento 35563 vs 35615, Trocar
  senha/Configurações 33456 vs 33547. This confirms the duplication is
  already causing real drift, not just a theoretical risk.
- Decide during implementation whether `flows.json` stays committed to git
  (regenerated and diff-checked, as assumed above) or becomes a build
  artifact that's gitignored and always regenerated — the task above assumes
  it stays committed because `tests/test_node_red_flow.py` and the Node-RED
  editor import both currently depend on a real file being present in the
  repo; revisit if that assumption turns out to be wrong during
  implementation.
