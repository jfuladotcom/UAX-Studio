# Updating UAX Studio on GitHub

This folder contains the current application and the files needed to update
[jfuladotcom/UAX-Studio](https://github.com/jfuladotcom/UAX-Studio), whose default
branch is `main`. Nothing has been committed or pushed by preparing this folder.

## Included

- Current application code, templates, styles, scripts, prompts, and migrations.
- Unit, integration, and optional browser tests.
- Runtime and development requirements, launch scripts, and configuration example.
- README, tutorial, MIT license, disclaimer, dependency notices, and existing social-preview assets.
- GitHub Actions checks, line-ending configuration, and Git ignore rules.
- Empty placeholders for local database, uploads, and exports directories.

Local databases, the session secret, personal settings, uploaded sources, generated
exports, virtual environments, caches, development reports, and Git history are
excluded. A fresh launch creates its own local state and fictional demo.

## Update the existing repository

1. Clone `https://github.com/jfuladotcom/UAX-Studio.git` into a separate folder using
   GitHub Desktop or `git clone`. If you already have a clone, save any pending
   work and pull the latest changes first.
2. Copy the **contents** of this prepared folder into the root of that clone,
   replacing matching files. `run.py` and `README.md` belong at the repository
   root. Include files beginning with a dot and the `.github` folder. Preserve
   the clone's `.git` folder.
3. Remove the obsolete tracked files listed below from the clone. Copying new
   files over old files does not remove them automatically. Preserve any newer
   work you added to GitHub after this package was prepared.
4. Review the changes in GitHub Desktop or with `git status` and `git diff --stat`.
5. Commit with a message such as `Update UAX Studio brief editing and workflow`,
   then push to `origin/main`. If branch protection requires a pull request,
   publish an update branch and open a pull request instead.
6. Check the repository's **Actions** tab for the CI result.

This folder is source code, not an archive: upload its contents rather than
placing the entire folder or a ZIP inside the repository. GitHub Desktop or Git
also handles the dotfiles and deletions needed for a complete update.

## Obsolete files

These files exist in the reference repository at commit
`de222b7c758f48401f3c89647bcd9b9d4d494ff3` but are absent from the current app:

- `app/prompts/fallback_contract.md`
- `app/prompts/fallback_simple_mode_contract.md`
- `app/prompts/fallback_simple_mode_synthesis.md`
- `app/prompts/fallback_synthesis.md`
- `app/prompts/simple_mode_contract_suggestions.md`
- `app/prompts/simple_mode_synthesis.md`
- `app/static/js/synthesis.js`
- `app/templates/projects/synthesis.html`

## Verify or run the app

Follow [README.md](README.md) to create a virtual environment and start the app.
To run the checks with that environment's Python:

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m compileall -q app tests run.py
python -m pytest
```

The browser test additionally needs Node 22+ and Edge, Chromium, or Chrome; it is
skipped when the browser or Node is unavailable. The app itself needs neither.
