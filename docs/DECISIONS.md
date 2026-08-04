# Decision log

Why things are the way they are. Revisit deliberately, not accidentally.

## Self-host over a free tier

Every "free" bot host has degraded — Heroku and Replit killed their always-on
free tiers, Railway moved to trial credit. A container on hardware already
running has no cold starts, no sleep behavior, and no expiry.

## Hand-built Unraid template, not Compose or a CA app

Requested constraint. Community Applications has no maintained app for running
an arbitrary Python daemon; the generic "run a script" containers there are
years stale and cron-oriented. A user template is a first-class Unraid citizen —
it appears in the template dropdown and is captured by CA Appdata Backup.

## GHCR image, not a "code release" Unraid pulls

Unraid pulls container images, not source archives. Wiring updates through
GHCR + digest comparison is the only path that makes the Docker tab's update
check work. GitHub releases are cut alongside for human-readable notes.

## Web server inside the bot process, not a separate nginx container

A genuinely static page cannot read a live SQLite file from the browser. The
alternative was exporting a JSON snapshot on every change and serving the
directory with nginx — that adds a container, a sync step, and a staleness
window. Embedding aiohttp keeps it one container with no lag. The page itself is
still plain static HTML.

## SQLite accessed synchronously

Tens of rows, single writer, single process. `aiosqlite` would add a dependency
and an await ceremony to queries that complete in microseconds. Revisit only if
this ever serves multiple guilds at real volume.

## Link buttons, not interactive components

`ButtonStyle.link` raises no interaction, so a pinned board keeps a working
Donate button indefinitely without registering a persistent view on startup.
Switching to a callback button would break every already-pinned message.

## Donate link stored per campaign, with an env default

`DONATE_URL` seeds new campaigns, but each row carries its own `link` column so
separate fundraisers can point at separate Givebutter pages. Added by guarded
`ALTER TABLE` against the live database.

## Manual ledger, not a Givebutter API integration

`/fund add` is entered by hand. Givebutter has webhooks, and wiring them would
make the numbers authoritative rather than honor-system — but that requires an
inbound authenticated endpoint, which conflicts with the current no-write-path
posture. Deferred, not rejected. See "Open threads".

## Web sheet design: drafting vernacular

The subject is a makerspace, so progress is drawn as an engineering **dimension
line** — extension ticks, inward arrowheads, a dimensioned value — against a
ruler scale on quadrille ground, with a title block at the foot of the sheet.
Chosen over a rounded progress bar because the shop's own drawing conventions
are more specific to this project than a generic tracker aesthetic.

Tokens: paper `#FBFAF6`, grid `#D2E1E7`, ink `#101A22`, graphite `#61727C`,
rule `#C4CBCE`, cut-red `#C8102E`, met-green `#157F5B`. Type is IBM Plex —
Condensed for display, Sans for body, Mono for all data and labels.

The one third-party call on the page is Google Fonts. Dropping the two `<link>`
tags falls back to system sans; layout holds, character is lost.

## Open threads

- **Givebutter webhooks** would replace manual entry with real donation events.
  Needs an authenticated inbound route and signature verification.
- **Donor privacy.** The sheet publishes the six most recent donor names per
  campaign to the open internet. People who gave a name in a Discord server did
  not necessarily agree to that audience. `SHOW_DONORS=false` is the switch;
  the default deserves a deliberate decision.
- **Role-based gating** instead of Manage Server — sketch is in
  `docs/DEPLOYMENT.md`, not yet applied.
- **Archived forum threads** drop out of cache and silently stop board updates.
  Unhandled.
- **No test suite.** Verification is `py_compile` plus a manual smoke test.
