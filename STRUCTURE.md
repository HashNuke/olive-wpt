# WPT output structure

The application creates one directory for every WPT test that Olive actually
discovers and runs. It does not create directories for arbitrary files in the
shared WPT checkout or for tests classified as non-applicable.

The directory preserves the complete WPT-relative path. The final `.html`,
`.xhtml`, or other test filename becomes a directory name:

```text
tests/css/css-backgrounds/example-1.html/
tests/css/css-images/example-1.html/
```

This prevents collisions between equal filenames in different WPT
directories.

## Per-test files

Each test directory contains:

```text
tests/css/css-backgrounds/example-1.html/
  metadata.json
  approved-olive.png
  approved-chrome.png
  approved-olive-vs-chrome.png
  wpt-source.png
  wpt-reference-0.png
  wpt-source-vs-reference-0.png
  new-olive.png
  current-chrome.png
  new-olive-vs-approved.png
  new-olive-vs-chrome.png
  current.json
```

`metadata.json` is committed and contains stable test identity and approval
metadata:

```json
{
  "schema_version": 1,
  "olive_version": "0.1.0+<git-sha>",
  "reference_browser": "chromium",
  "reference_browser_version": "<exact-version>",
  "wpt_url": "https://wpt.live/css/css-backgrounds/example-1.html",
  "wpt_local_path": "css/css-backgrounds/example-1.html",
  "capture": {
    "viewport_width": 800,
    "viewport_height": 600,
    "device_scale_factor": 1
  }
}
```

`wpt_local_path` is relative to the WPT repository root. It must not contain
`external/wpt/` or an absolute checkout path.

When the test is approved, commit:

- `approved-olive.png`
- `approved-chrome.png`
- `approved-olive-vs-chrome.png`
- the updated `metadata.json`

The approved Chromium image and its diff are the approval-time evidence. They
are not the Olive pass/fail oracle.

The current run overwrites, without committing:

- `wpt-source.png`
- `wpt-reference-<index>.png`
- `wpt-source-vs-reference-<index>.png`
- `new-olive.png`
- `current-chrome.png`
- `new-olive-vs-approved.png`
- `new-olive-vs-chrome.png`
- `current.json`

If no approved Olive render exists, the test is pending approval. If an
approved render exists and `new-olive-vs-approved.png` is an exact match, the
test is approved. If it differs, the test is a deviation. Renderer and
infrastructure errors are separate failure states.

The root-level `current/result.json` may contain the aggregate report for the
latest overwrite, while each `current.json` contains the latest per-test
status and artifact information.
