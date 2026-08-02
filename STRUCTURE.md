# WPT output structure

The Olive WPT runner creates one directory for every WPT test it discovers and
runs. It does not copy WPT source files into this repository. The source remains
in the shared external WPT checkout, and the directory preserves the complete
WPT-relative path under `outputs/`.

The test filename becomes a directory name with its extension spelled out:

```text
outputs/css/css-backgrounds/example-1-html-test/
outputs/css/css-images/example-1-html-test/
outputs/css/CSS2/floats-clear/float-applies-to-008a-xht-test/
```

This prevents collisions between equal filenames in different WPT directories
and makes the directory visibly distinct from a source-test directory.

## Per-test files

Each test directory uses this four-file contract:

```text
outputs/css/css-backgrounds/example-1-html-test/
  result.png
  reference.png
  result-vs-reference.png
  metadata.json
```

`result.png` is Olive's render and `reference.png` is the capture from the
reference browser. The browser name and exact version belong in `metadata.json`,
not in the image filename. `result-vs-reference.png` is a generated comparison
image for local review and is ignored by Git.

The approved Git state contains only:

- `result.png`
- `reference.png`
- `metadata.json`

The committed `result.png` is the approved Olive baseline. A later run
overwrites the worktree copy at the same path; Git then exposes a binary change
against the approved baseline. No separate approved-render diff is needed.

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

`wpt_local_path` is relative to the WPT repository root. It must not contain
`external/wpt/` or an absolute checkout path.

If no committed `result.png` and approved `metadata.json` exist, the test is
pending approval. If they exist and the current `result.png` differs from the
committed version, the test is a deviation. The application can derive these
states from Git plus the current output files; the generated reference diff is
review evidence, not an approval artifact.

Renderer and infrastructure errors are reported separately from pending,
approved, and deviation states.
