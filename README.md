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

The curated WPT inventory is maintained in [`wpt_paths.txt`](wpt_paths.txt),
at the repository root so the Olive submodule and the review application share
one source of truth. The home page reads this file and links each entry to its
review page, where the Olive and Chrome renders are shown when available. It
does not enumerate Git or output files. Review pages use
`/test-report/view?path=<wpt-test-path>` and provide HTMX controls for switching
between renders and approving or unapproving the Olive result.

Each run writes current comparison metrics to ignored `current.json`. Approval
stores the approved result hash and diff baseline in `metadata.json`; the review
page reports unchanged, improved, equal, and regressed results without treating
metadata-only changes as render changes.
