# fundbot

A Discord bot for tracking makerspace fundraising campaigns, plus a public
read-only web page that shows progress toward each goal.

Organizers log donations with slash commands. The bot stores them in SQLite, and
a small web server in the same container shows the same data as a status sheet.
Discord is the only way to change anything; the web page is read-only.

## Running it

The image is published to GHCR on every push to `main`:

```
docker run -d --name fundbot   -e DISCORD_TOKEN=...   -e GUILD_ID=...   -p 8099:8099   -v /mnt/user/appdata/fundbot:/data   ghcr.io/adman234/fundbot:latest
```

`/healthz` returns `ok` once the web server is up.

## Commands

| Command | Who | Does |
|---|---|---|
| `/fund list` | anyone | every campaign, with progress and donate links |
| `/fund show <name>` | anyone | one campaign in detail |
| `/fund create <name> <goal> [currency] [link]` | Manage Server | create or update a campaign |
| `/fund link <name> [url]` | Manage Server | set or clear the donate link |
| `/fund add <name> <amount> [donor]` | Manage Server | log a donation |
| `/fund board <name>` | Manage Server | pin a live-updating tracker |
| `/fund undo <name>` | Manage Server | remove the most recent donation |

## Environment

| Var | Default | Notes |
|---|---|---|
| `DISCORD_TOKEN` | | required |
| `DONATE_URL` | | default link applied to new campaigns |
| `GUILD_ID` | | set for instant slash-command sync |
| `DB_PATH` | `/data/fundraiser.db` | |
| `WEB_PORT` | `8099` | |
| `STATIC_DIR` | `/app/web` | |
| `SHOW_DONORS` | `true` | `false` hides names on the web sheet only |

## Kiosk layout

Append `?kiosk` to the sheet URL on the shop touchscreen. The masthead then
shows a 180px QR code beside a stack of controls:

| Control | Kiosk | Everywhere else |
|---|---|---|
| Dark / Light | button | button |
| Open GUI | button, opens `kioskmgr://show` | hidden |
| Scan to give | plain caption | link to the donate URL |

Visitors give from their own phones rather than opening the payment page on a
shared screen. Without the parameter the page is unchanged; `?kiosk=0` turns it
off. See `docs/DECISIONS.md` for why this is a URL parameter rather than screen
detection, and why the Open GUI button is a link rather than a local request.

## Releasing

Push to `main` publishes `:latest`. Tagging publishes a pinned version and a
GitHub release:

```
git tag v1.1.0 && git push --tags
```

## Caveat

`/fund add` is an honor-system ledger, not a payment record. Anyone permitted to
run it can enter any figure. Treat the donation platform as the source of truth.
