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

The application currently provides only its FastAPI/static-asset scaffold.
Pending, Approved, and Deviations routes will be added in a later checkpoint.
