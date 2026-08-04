# CLAUDE.md

Context for Claude Code working in this repo. Read `docs/DECISIONS.md` before
proposing architectural changes — several obvious-looking refactors were already
considered and rejected for reasons recorded there.

## What this is

A Discord bot that tracks fundraising campaigns for a makerspace, plus a public
read-only web sheet at `fundraising.adman.casa` showing progress toward goals.

Slash commands write to SQLite. An aiohttp server in the same process reads that
database and serves a static HTML page plus one JSON endpoint. Discord is the
only write path; the web side exposes no mutations.

## Layout

```
bot.py              Discord client, slash commands, SQLite schema + migrations
webserver.py        aiohttp app: /api/campaigns, /healthz, / (static sheet)
web/index.html      Self-contained page — CSS and JS inline, no build step
Dockerfile          Published to GHCR by CI
.github/workflows/publish.yml
docs/               Deployment, design rationale, decision log
```

Single-process design: `webserver.start()` is invoked from the bot's
`setup_hook`, so the HTTP listener binds before the gateway connects and a port
conflict fails fast instead of after login.

## Constraints that are load-bearing

- **`web/index.html` stays single-file.** No bundler, no framework, no npm. It
  is copied into the image as-is and edited by hand. Keep CSS in `<style>` and
  JS in `<script>`.
- **No write endpoints on the web server.** The page is public and
  unauthenticated. Adding a POST route changes the security posture entirely and
  needs an explicit decision, not a drive-by commit.
- **Schema changes need a guarded migration.** There is a live database with
  real donation history. Follow the existing `PRAGMA table_info` pattern in
  `bot.py`; never drop or recreate a table.
- **Link buttons only.** `donate_view()` builds a `ButtonStyle.link` button,
  which raises no interaction event. That is why pinned boards keep working
  buttons across restarts with no persistent-view registration. Any button with
  a callback would need `bot.add_view()` on startup and would break existing
  pinned messages.
- **All progress rendering routes through `respond_with()`.** This exists so the
  donate link cannot be present in one command's output and missing from
  another's. Do not call `build_embed()` directly in a new command.

## Conventions

- Python 3.12, stdlib `sqlite3` used synchronously. The dataset is tiny (tens of
  rows); do not introduce an async DB layer or an ORM for it.
- Privileged commands carry `@app_commands.checks.has_permissions(manage_guild=True)`.
  `list` and `show` are deliberately public.
- User-facing copy: sentence case, plain verbs, no apology in error strings.
  Empty states say what to do next.
- Money is `REAL` and formatted at the presentation layer with `:,.2f`.
  `currency` is a cosmetic prefix string; no conversion happens anywhere.

## Testing

There is no test suite. Verification is manual:

```bash
python -m py_compile bot.py webserver.py     # syntax
docker build -t fundbot:dev .                # image builds
```

For runtime checks, `/healthz` returns `ok` and `/api/campaigns` returns JSON
without needing a Discord connection — useful for validating web changes.

Slash command edits require a restart plus a re-sync. With `GUILD_ID` set, sync
is instant; without it, global propagation takes up to an hour.

## Known sharp edges

- `on_ready` fires on every gateway resume, not just first connect. Sync is
  guarded behind the `_synced` flag — keep it that way.
- `guild.get_channel_or_thread()` is required (not `get_channel`) because boards
  posted in forum posts store the thread ID. Archived threads fall out of cache
  and the board silently stops updating until someone posts in it.
- `refresh_board` swallows `NotFound`/`Forbidden` and nulls the stored IDs. That
  is intentional self-healing, not a missing error path.
- `/fund add` is an honor-system ledger. Anyone with Manage Server can enter any
  figure, and `undo` only pops the single most recent row. The numbers are
  published publicly, so treat Givebutter as the source of truth.

## Deployment shape

Runs as a container on an Unraid server, deployed via a hand-built user template
(not Docker Compose, not a Community Applications app). CI publishes to GHCR;
Unraid's update check compares registry digests against the running image.

Full host-specific details in `docs/DEPLOYMENT.md`.
