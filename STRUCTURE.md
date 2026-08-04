# WPT output structure

The reference-baseline generator and Olive WPT runner create one directory for
each WPT path. They do not copy WPT source files into this repository. The source
remains in the shared external WPT checkout, and the directory preserves the
complete WPT-relative path under `outputs/`.

The source checkout tag used for the inventory is recorded in `WPT_REVISION`.
`bin/update-wpt` refreshes that tag, the inventory, and missing Chromium
references as one repeatable operation. Paths whose references still fail are
listed in `failed-references.txt` and omitted from the active `wpt_paths.txt`
until a later refresh succeeds.

The test filename becomes a directory name with its extension spelled out:

```text
outputs/css/css-backgrounds/example-1-html-test/
outputs/css/css-images/example-1-html-test/
outputs/css/CSS2/floats-clear/float-applies-to-008a-xht-test/
```

This prevents collisions between equal filenames in different WPT directories
and makes the directory visibly distinct from a source-test directory.

## Per-test files

Each test directory can contain these artifacts:

```text
outputs/css/css-backgrounds/example-1-html-test/
  result.png
  reference.png
  result-vs-reference.png
  metadata.json
  review-state.json
```

`reference.png` is generated once by
`bin/generate-wpt-reference-screenshots.py` with Playwright Chromium from
`https://wpt.live/<WPT-relative-path>`, using an 800x600 viewport, device scale
factor 1, network-idle navigation, settled fonts/images, and a 3-second deadline.
The generator writes a JSON report under ignored `current/`; it records timeout
and request-failure outcomes instead of inventing a screenshot. `result.png` is
Olive's render from the normal local sweep. No Chromium process is started by
that sweep. `result-vs-reference.png` is a generated comparison image for local
review and is ignored by Git. The ignored `current.json` file records the latest
comparison metrics:

```json
{
  "schema_version": 1,
  "current_different_pixels": 123,
  "current_total_pixels": 480000,
  "current_diff_percent": 0.025625
}
```

The ignored `current/result.csv` file is the home-page status index. It has
`status,path` columns, with one `PASS`, `FAIL`, `REVW`, `UNKN`, or `NONE` row per
WPT-relative test path.

The ignored `current/progress.json` file records the latest status delta:
`new_passes`, `regressions`, `review_needed`, `unrendered`, `unreviewed`, and
`total`. The normal Olive lint gate blocks nonzero approved regressions; an
engine-feature checkpoint additionally requires `bin/check-wpt-progress
--engine` to report at least one new pass.

The generated baseline commit contains `reference.png` files. An approved test
may additionally contain:

- `result.png`
- `metadata.json`

A rejected or changed result may additionally contain a tracked
`review-state.json`; its local `result.png` remains uncommitted until that
specific result is approved. Approval deletes `review-state.json` and permits
the matching `result.png` to be committed.

The committed `result.png` is the approved Olive baseline when present. A later
run overwrites the worktree copy at the same path; Git then exposes a binary
change against the approved baseline. No separate approved-render diff is needed.

`metadata.json` contains stable test identity and approval metadata:

```json
{
  "schema_version": 1,
  "status": "approved",
  "olive_version": "0.1.0+<git-sha>",
  "reference_browser": "chromium",
  "reference_browser_version": "<exact-version>",
  "wpt_url": "https://wpt.live/css/css-backgrounds/example-1.html",
  "wpt_local_path": "css/css-backgrounds/example-1.html"
}
```

When a result is approved, metadata may also record the approved result hash and
comparison baseline: `approved_result_sha256`, `approved_diff_percent`,
`approved_different_pixels`, and `approved_total_pixels`. The reference-baseline
comparison itself is exact RGBA equality; approval metadata is separate review
state.

`review-state.json` is tracked review state for a non-approved render. It stores
the rejection reason, current Olive/reference hashes, and comparison metrics.
Approval deletes it. The pre-commit hook prevents `result.png` from being
committed unless the staged metadata approves that exact result hash.

`wpt_local_path` is relative to the WPT repository root. It must not contain
`external/wpt/` or an absolute checkout path.

If no committed `result.png` and approved `metadata.json` exist, the test is
pending approval. A missing Olive `result.png` is `NONE`; an available result
without a review decision is `UNKN`; a rejected current result is `FAIL`; a
changed or improved result after review is `REVW`; and an exact approved result
is `PASS`. The application can derive these states from Git plus the current
output files; the generated reference diff is review evidence, not an approval
artifact.

Renderer and infrastructure errors are reported separately from pending,
approved, and deviation states.
