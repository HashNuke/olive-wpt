# Olive browser-engine WPT results

This repository contains the Web Platform Test (WPT) rendering results used to
evaluate Olive, a browser engine that renders HTML, CSS, SVG, and images.
Each selected WPT is rendered by Olive and Chromium under the same conditions so
that we can compare the resulting pixels and track browser-compatibility work.

## What the results show

For each WPT, the review application can show:

- the current Olive render;
- the Chromium reference render;
- the pixel difference between them;
- comparison metrics such as differing-pixel count and diff percentage; and
- human or AI review feedback.

The output artifacts are organized under [`outputs/`](outputs/) using the WPT
path. A test output normally contains `result.png` from Olive,
`reference.png` from Chromium, `current.json` with the current comparison, and
`metadata.json` when an Olive render has been approved. `review-state.json`
contains an outstanding rejection or review request. Review images are local,
ignored artifacts generated when needed for visual review.

## Result statuses

- `PASS` — the current Olive render matches the approved Olive render.
- `FAIL` — the render failed, or the current render was rejected.
- `REVW` — the render differs from an approved or previously rejected render and
  needs review.
- `UNKN` — an Olive render exists but has not been approved or rejected.
- `NONE` — no Olive render is available.

An approval establishes the current Olive PNG as the baseline for future
comparisons. A lower pixel difference can be useful evidence, but visual review
is still required before accepting a changed render.

## Review the results

Start the local review application from this directory:

```sh
bin/dev
```

Then open `http://localhost:8000`. The test index and `/test-results` page show
the available results, comparisons, statuses, and review feedback. Individual
test pages provide larger render views and controls to approve, reject, or
unapprove a result.

For an AI-assisted visual review, provide the Gemini API key and pass one or
more WPT paths or directory prefixes:

```sh
GEMINI_API_KEY=... bin/review-wpt-output css/css-text/text-indent/
```

The review command recreates the local comparison image, sends it with the
render metrics for visual analysis, saves the decision and feedback in the
test's `review-state.json`, and updates the results index. An AI `PASS` remains
`REVW` until a human approves it in the review application.

## Run and update results

The parent Olive repository runs the selected WPT rendering checks and writes
the resulting artifacts here. After a run, refresh the review application to
inspect the latest results. Keep approved result artifacts together with their
approval metadata so that the recorded baseline remains verifiable.
