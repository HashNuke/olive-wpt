# Olive WPT output review

This repository stores the review application and public approved WPT render
artifacts for Olive. It is mounted into Olive as the `wpt-outputs` submodule.

Run the development server with:

```sh
bin/dev
```

Before committing output changes, install the repository's pre-commit hook:

```sh
bin/install-hooks
```

The hook runs `bin/lint`. It requires staged `metadata.json` files to contain
`"status": "approved"`, and rejects staged `result.png` files unless their
metadata approves that exact PNG hash. Other staged files are not blocked by
this check.

The application currently provides its FastAPI/static-asset scaffold and a
directory-style home page. Pending, Approved, and Deviations routes will be
added in a later checkpoint.

The WPT reftest inventory is maintained in [`wpt_paths.txt`](wpt_paths.txt),
at the repository root so the Olive submodule and the review application share
one source of truth. It contains WPT-relative source files with literal
`<link>` elements declaring `rel="match"` or `rel="mismatch"`; filename suffixes
do not determine inclusion. The home page reads this file and links each entry
to its review page, where the Olive and Chrome renders are shown when
available. It does not enumerate Git or output files. Review pages use
`/test-report/view?path=<wpt-test-path>` and provide HTMX controls for switching
between Olive, reference, and in-memory comparison tabs, with links that open
the images independently and controls for approving or unapproving the Olive
result.

The source checkout tag is recorded in [`WPT_REVISION`](WPT_REVISION). Run
[`bin/update-wpt`](bin/update-wpt) from this repository to fetch the newest
`merge_pr_*` tag, keep the shared checkout at that tag in a one-commit shallow
detached state, regenerate `wpt_paths.txt`, prune output directories for paths
that no longer exist, and generate missing Chromium `reference.png` files.
Tests whose references still fail generation are written to
`failed-references.txt` and removed from the active inventory until a later
updater run succeeds for them.

Each run writes current comparison metrics and the WPT run outcome to ignored
per-test `current.json` files. Run [`bin/build-db`](bin/build-db) to rebuild the
ignored Peewee/SQLite `data.sqlite` homepage index from the inventory and each
test's PNG and JSON files. The homepage reads that database. The test page
reads its own flat JSON files directly, while page actions update both the JSON
files and the corresponding database row. The home page prefixes each test
with the same status: `PASS` means the current
Olive result matches an approved hash, `FAIL` means it matches a recorded
rejection, `REVW` means it changed after approval or rejection, `UNKN` means an
Olive result exists but has not been reviewed, and `NONE` means no Olive result
exists. The home page provides tabs for `ALL`, `PASS`, `FAIL`, `REVW`, `UNKN`,
and `NONE` with counts. Approval stores the approved result hash and diff baseline in
`metadata.json`. A rejected render stores its reason and exact result/reference
hashes in a tracked per-test `review-state.json`; the local `result.png` is
deliberately not committed while metadata is pending. Approving the render
updates `metadata.json`, deletes `review-state.json`, and allows the matching
`result.png` to be committed.

Each status write also updates ignored `current/progress.json` with the latest
`new_passes`, `regressions`, `review_needed`, `unrendered`, and `unreviewed`
counts. The Olive repository lint gate blocks approved regressions. An engine
feature checkpoint must additionally run `bin/check-wpt-progress --engine`,
which requires at least one newly passing WPT test.

Run the parent repository's WPT test command against the committed path list.
Each completed test updates its own JSON files and SQLite row immediately, so a
single full run can be resumed or focused with `OLIVE_WPT_PATHS`. Run
`bin/build-db` when the inventory itself changes or when a full read-model
rebuild is explicitly needed.
