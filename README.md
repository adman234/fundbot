# fundbot

Discord fundraising tracker with a public status sheet.

Slash commands write to SQLite; a read-only aiohttp server renders the same data
as a static page. The only mutation path is Discord — the web side exposes no writes.

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
| `DISCORD_TOKEN` | — | required |
| `DONATE_URL` | — | default link applied to new campaigns |
| `GUILD_ID` | — | set for instant slash-command sync |
| `DB_PATH` | `/data/fundraiser.db` | |
| `WEB_PORT` | `8099` | |
| `STATIC_DIR` | `/app/web` | |
| `SHOW_DONORS` | `true` | `false` hides names on the web sheet only |

## Kiosk layout

Append `?kiosk` to the sheet URL on the shop touchscreen. The Donate button is
hidden and the QR code grows to 260px, so visitors give from their own phones
instead of opening the payment page on a shared screen. Without the parameter
the page is unchanged; `?kiosk=0` turns it off. See `docs/DECISIONS.md` for why
this is a URL parameter rather than screen detection.

## Releasing

Push to `main` publishes `:latest`. Tagging publishes a pinned version and a
GitHub release:

```
git tag v1.1.0 && git push --tags
```

## Caveat

`/fund add` is an honor-system ledger, not a payment record. Anyone permitted to
run it can enter any figure. Treat the donation platform as the source of truth.
