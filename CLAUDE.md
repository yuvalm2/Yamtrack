# Yamtrack fork — Claude instructions

A private fork of [Yamtrack](https://github.com/FuzzyGrim/Yamtrack) (AGPL-3.0),
carrying local UI changes. Deployed as `media.cogniflow.biz` by the Orchestra
stack, which builds it from this checkout — see "Deployment" below.

## This is a patch series on an upstream tag, not a long-lived divergence

`main` is an upstream release tag plus a short series of our own commits. The
baseline tag is always present, so our entire patch set is:

```
git diff v0.26.3..main          # replace with the current base tag
```

Keep it that way. Every local change should be small, self-contained, and
obvious in that diff — new files wherever possible, so upstream's own files
stay untouched and rebases stay cheap.

### Current local changes

- **"Watched up to here"** — a per-episode button that marks everything from
  the start of a season through that episode. `Season.watch_upto()` in
  `src/app/models.py`, `episode_watch_upto` in `src/app/views.py`.
- **Notes & links** — `MediaNote`, many per item, each a text note or a titled
  URL. Views live in their own module, `src/app/notes.py`. `Media.notes`
  (upstream's single free-text field) now also renders through `urlize`.

## Rebasing onto a new upstream release

```
git fetch upstream --tags
git rebase <new tag>
```

Two things need care:

1. **`src/static/css/main.css` is a generated file.** Do not resolve conflicts
   in it by hand. Take upstream's copy, then re-run the build:
   ```
   npm install && npm run build:css
   ```
   Upstream regenerates this file with a globally installed CLI and no
   manifest; `package.json` here pins the version that produced the baseline so
   the diff stays limited to our added classes. **A Tailwind class that is not
   in `main.css` silently has no styles** — nothing errors, the element just
   renders unstyled. Rebuild whenever you add one.

2. **`src/app/admin.py` auto-registers every model in the app** with
   `MediaAdmin`, whose `list_display` assumes Media's `status`/`score`. Any new
   non-Media model must get its own ModelAdmin *and* be added to
   `SpecialModels`, or `manage.py check` fails.

## Verifying a change

The project needs Python >= 3.12. On yuval2020-PC neither the system Python
(3.11/3.14) nor WSL's (3.10) qualifies, so let uv fetch its own:

```
py -3.11 -m uv sync --locked --no-default-groups --group test
SECRET=test-only-key py -3.11 -m uv run python src/manage.py check
SECRET=test-only-key py -3.11 -m uv run python src/manage.py makemigrations --check --dry-run
SECRET=test-only-key py -3.11 -m uv run python src/manage.py test app --parallel
py -3.11 -m uv run ruff check src && py -3.11 -m uv run ruff format --check src
```

`SECRET` is required — Django will not start without it.

**Hand-written migrations must be confirmed with `makemigrations --check
--dry-run`**, which reports "No changes detected" only when the migration
matches the models exactly.

### Known-failing tests on a clean checkout

Measured against pristine `v0.26.3`, so do not attribute these to your change:

- `app.tests.views.test_journal` — **flaky under `--parallel`**, failed 4 of 4
  pristine runs. `setUp` saves the movie twice in immediate succession, so the
  two history rows can tie on `history_date` and the diff direction flips.
  Passes consistently when the module is run without `--parallel`.
- `integrations.tests.test_steam_update.ImportSteamUpdate.test_overwrite_updates_newest_game_instance`
  — flaky the same way (two rows created back to back, "newest" ambiguous).
- `*.test_integration.IntegrationTest` (`app` and `lists`) — needs
  `uv run playwright install`; errors in `setUpClass` without the browsers.
- `app.tests.providers.test_metadata.Metadata.test_hardcover_book` — asserts a
  live Hardcover genre list that has since changed at the publisher. **Skipped
  locally** so a red build here means something; drop the decorator on the next
  rebase and see whether upstream has fixed it.
- `integrations`/`users` import-schedule tests — 4 errors, pre-existing.

Templates are **not** covered by the linters or the system check, so a bad
filter or a missing `{% load %}` only shows up at runtime. Exercise a changed
template with a view test.

## CI

Upstream's workflows are inherited and run here too. `app-tests.yml` and
`lint.yml` fire on every push to `main` and are worth keeping — CI runs the full
suite including the Playwright tests, which the local setup above does not.

**`.github/dependabot.yml` is rewritten, not inherited.** Upstream's version is
daily with `open-pull-requests-limit: 30` and groups that cover only
minor/patch, so every major bump gets its own PR — 9 PRs in six minutes on this
repo's first day. Ours groups everything (majors included, which needs an
explicit `update-types`) with a limit of 1, so each ecosystem has a single
standing PR that Dependabot keeps updating until it is merged or closed.

Only `uv` and `docker` are enabled — the two that reach the deployed image.
Dependabot cannot group across ecosystems, so two standing PRs is the floor;
drop the `docker` entry if you want exactly one.

**Prefer rebasing over merging one of those PRs.** Merging diverges `uv.lock`
from upstream, which is what this fork is structured to avoid, and an unpinned
transitive bump is a deploy — FlowDeck rejected every card edit for hours on
2026-09-22 that way. Rebase onto an upstream release that already carries the
bump; merge here only for something that cannot wait.

`codeql.yml` (weekly) and `stale.yml` (daily) crons are also inherited and do
nothing useful here, but they are harmless and left alone to keep the diff
small.

## Deployment

Orchestra builds this repo as the `yamtrack` service (`build: ../Yamtrack`), so
the checkout must exist beside Orchestra's on the live host. Deploy by pushing
here and letting Orchestra's `redeploy` pull — never edit on the host, and
never commit there: a local commit diverges from origin and breaks
`pull --ff-only`.

The SQLite DB lives in the `yamtrack-data` volume, not in this repo, and is
copied to R2 hourly by the `yamtrack-backup` sidecar. Switching the service
from a pinned image to a build does not touch that volume.
