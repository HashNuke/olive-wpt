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

The hook runs `bin/lint`. It examines only staged `metadata.json` files and
rejects the commit unless each one contains the exact JSON field
`"status": "approved"`. Other staged files are not blocked by this check.

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

Each run writes current comparison metrics to ignored `current.json` and a
`current/result.csv` status index. The CSV has `status,path` columns and uses
`PASS`, `FAIL`, or `UNKN` for each WPT-relative test path. The home
page prefixes each test with `PASS`, `FAIL`, or `UNKN`: only an exact match with
an approved result is `PASS`, a changed approved result is `FAIL`, and a test
without an approved baseline is `UNKN`. Approval stores the approved result hash
and diff baseline in `metadata.json`. Local review rejections are stored in the
ignored `current/rejections.txt` path list, so agents can work from the list
without adding rejection state to the repository. A locally rejected test is
shown as `FAIL` even when it has no previously approved render.
