# olive-wpt

## Project purpose

`olive-wpt` is the public review repository for Olive's WPT rendering output.
Olive includes this repository at the root path `wpt-outputs` as a Git
submodule. The FastAPI application reads per-test metadata and screenshots,
then presents the review workflow for pending approvals, approved renders, and
rendering deviations.

This repository is not part of Olive's portable production renderer. Do not add
R2, filesystem, or web-server dependencies to Olive production code because of
this application.

## Repository hygiene

- Keep approved artifacts and their metadata under `tests/` following
  `STRUCTURE.md`.
- Commit only reviewed approved renders, approval-time Chromium evidence, and
  stable metadata. Current-run renders and reports are ignored.
- Preserve the WPT-relative path in every test directory; do not flatten test
  names or use absolute checkout paths.
- Never silently replace an approved render. Approval is an explicit reviewed
  Git change.
- Do not commit credentials, local WPT checkout paths, virtual environments,
  caches, or generated current-run artifacts.
- Keep application code, templates, CSS, and JavaScript in their dedicated
  locations. Do not put generated output in the static asset directories.
- Use `uv sync` to install dependencies and `bin/dev` to run the local app.
- Make small commits with a clear description. Validate the application and
  inspect the Git diff before committing.

## Labnotes

For research or implementation work, create a local worklog with:

```sh
bin/create-labnotes 2-4-word-task-name
```

Write what was tried, what worked, failures, barriers, workarounds, and
decisions in the resulting `worklogs/` file. Worklogs are intentionally ignored
in this public output repository; the parent Olive repository owns any required
checkpoint labnotes. Do not create labnotes for status checks or one-off script
execution requests.
