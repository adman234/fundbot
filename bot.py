#!/usr/bin/env python3
"""
Discord fundraising tracker + read-only web sheet.

Env:
  DISCORD_TOKEN  (required)  bot token
  DONATE_URL     (optional)  default donate link applied to new campaigns
  DB_PATH        (optional)  default /data/fundraiser.db
  GUILD_ID       (optional)  numeric guild id -> instant slash-command sync
  WEB_PORT       (optional)  default 8099
  STATIC_DIR     (optional)  default /app/web
  SHOW_DONORS    (optional)  "false" hides donor names from the web sheet only
"""

import os
import socket
import sqlite3
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import webserver

TOKEN = os.environ["DISCORD_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "/data/fundraiser.db")
GUILD_ID = os.environ.get("GUILD_ID")
WEB_PORT = int(os.environ.get("WEB_PORT", "8099"))
STATIC_DIR = os.environ.get("STATIC_DIR", "/app/web")
SHOW_DONORS = os.environ.get("SHOW_DONORS", "true").lower() == "true"
DONATE_URL = os.environ.get("DONATE_URL", "").strip()

db = sqlite3.connect(DB_PATH)
db.execute("""
CREATE TABLE IF NOT EXISTS campaign (
    guild_id   INTEGER NOT NULL,
    name       TEXT    NOT NULL,
    goal       REAL    NOT NULL,
    currency   TEXT    NOT NULL DEFAULT '$',
    channel_id INTEGER,
    message_id INTEGER,
    PRIMARY KEY (guild_id, name)
)""")
db.execute("""
CREATE TABLE IF NOT EXISTS donation (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name     TEXT    NOT NULL,
    amount   REAL    NOT NULL,
    donor    TEXT,
    ts       TEXT    NOT NULL
)""")

# --- migration: donate link per campaign -------------------------------------
_cols = {row[1] for row in db.execute("PRAGMA table_info(campaign)")}
if "link" not in _cols:
    db.execute("ALTER TABLE campaign ADD COLUMN link TEXT")
db.commit()

bot = commands.Bot(
    command_prefix=commands.when_mentioned,
    intents=discord.Intents.default(),
    help_command=None,
)


# ---------- data helpers ----------

def get_campaign(guild_id: int, name: str):
    return db.execute(
        "SELECT name, goal, currency, channel_id, message_id, link "
        "FROM campaign WHERE guild_id=? AND name=?", (guild_id, name)
    ).fetchone()


def totals(guild_id: int, name: str):
    raised, count = db.execute(
        "SELECT COALESCE(SUM(amount),0), COUNT(*) FROM donation "
        "WHERE guild_id=? AND name=?", (guild_id, name)
    ).fetchone()
    return raised, count


def bar(pct: float, width: int = 22) -> str:
    filled = max(0, min(width, round(pct * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


def valid_link(url) -> bool:
    return bool(url) and url.startswith("https://")


def donate_view(url) -> discord.ui.View | None:
    """Link buttons raise no interaction, so this survives restarts as-is."""
    if not valid_link(url):
        return None
    v = discord.ui.View()
    v.add_item(discord.ui.Button(label="Donate", url=url,
                                 style=discord.ButtonStyle.link, emoji="\U0001F49B"))
    return v


def build_embed(guild_id: int, name: str) -> discord.Embed:
    _, goal, cur, _, _, link = get_campaign(guild_id, name)
    raised, count = totals(guild_id, name)
    pct = raised / goal if goal else 0.0

    e = discord.Embed(
        title=f"\U0001F3AF {name}",
        url=link if valid_link(link) else None,
        description=f"`{bar(pct)}`  **{pct * 100:.1f}%**",
        colour=discord.Colour.green() if pct >= 1 else discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    e.add_field(name="Raised", value=f"{cur}{raised:,.2f}")
    e.add_field(name="Goal", value=f"{cur}{goal:,.2f}")
    e.add_field(name="Remaining", value=f"{cur}{max(0.0, goal - raised):,.2f}")
    e.set_footer(text=f"{count} donation{'s' if count != 1 else ''} \u00b7 updated")

    recent = db.execute(
        "SELECT donor, amount FROM donation WHERE guild_id=? AND name=? "
        "ORDER BY id DESC LIMIT 5", (guild_id, name)
    ).fetchall()
    if recent:
        e.add_field(
            name="Recent",
            value="\n".join(f"{d or 'Anonymous'} \u2014 {cur}{a:,.2f}" for d, a in recent),
            inline=False,
        )

    if valid_link(link):
        e.add_field(name="Give", value=f"[Donate to {name}]({link})", inline=False)

    return e


async def refresh_board(guild: discord.Guild, name: str):
    """Edit the pinned tracker message, if one exists."""
    row = get_campaign(guild.id, name)
    if not row or not row[3] or not row[4]:
        return
    channel = guild.get_channel_or_thread(row[3])
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(row[4])
        await msg.edit(embed=build_embed(guild.id, name), view=donate_view(row[5]))
    except (discord.NotFound, discord.Forbidden):
        db.execute(
            "UPDATE campaign SET channel_id=NULL, message_id=NULL "
            "WHERE guild_id=? AND name=?", (guild.id, name))
        db.commit()


async def respond_with(interaction: discord.Interaction, name: str):
    """Single place that renders a campaign, so the donate link is never missed."""
    row = get_campaign(interaction.guild_id, name)
    await interaction.response.send_message(
        embed=build_embed(interaction.guild_id, name),
        view=donate_view(row[5]),
    )


async def name_autocomplete(interaction: discord.Interaction, current: str):
    rows = db.execute(
        "SELECT name FROM campaign WHERE guild_id=? AND name LIKE ? LIMIT 25",
        (interaction.guild_id, f"%{current}%")
    ).fetchall()
    return [app_commands.Choice(name=r[0], value=r[0]) for r in rows]


# ---------- commands ----------

fund = app_commands.Group(name="fund", description="Fundraising tracker")


@fund.command(name="create", description="Create or update a campaign goal")
@app_commands.checks.has_permissions(manage_guild=True)
async def create(interaction: discord.Interaction, name: str, goal: float,
                 currency: str = "$", link: str = None):
    if goal <= 0:
        return await interaction.response.send_message(
            "Goal must be greater than zero.", ephemeral=True)

    link = (link or DONATE_URL).strip() or None
    if link and not valid_link(link):
        return await interaction.response.send_message(
            "Donate link must start with https://", ephemeral=True)

    db.execute(
        "INSERT INTO campaign (guild_id, name, goal, currency, link) VALUES (?,?,?,?,?) "
        "ON CONFLICT(guild_id, name) DO UPDATE SET "
        "goal=excluded.goal, currency=excluded.currency, link=excluded.link",
        (interaction.guild_id, name, goal, currency, link))
    db.commit()
    await refresh_board(interaction.guild, name)
    await interaction.response.send_message(
        f"Campaign **{name}** set to {currency}{goal:,.2f}."
        + (f"\nDonate link: {link}" if link else "\nNo donate link set."),
        ephemeral=True)


@fund.command(name="link", description="Set or clear a campaign's donate link")
@app_commands.autocomplete(name=name_autocomplete)
@app_commands.checks.has_permissions(manage_guild=True)
async def link_cmd(interaction: discord.Interaction, name: str, url: str = None):
    if not get_campaign(interaction.guild_id, name):
        return await interaction.response.send_message(
            f"No campaign named **{name}**.", ephemeral=True)

    url = (url or "").strip() or None
    if url and not valid_link(url):
        return await interaction.response.send_message(
            "Donate link must start with https://", ephemeral=True)

    db.execute("UPDATE campaign SET link=? WHERE guild_id=? AND name=?",
               (url, interaction.guild_id, name))
    db.commit()
    await refresh_board(interaction.guild, name)
    await interaction.response.send_message(
        f"Donate link for **{name}** {'set to ' + url if url else 'cleared'}.",
        ephemeral=True)


@fund.command(name="add", description="Log a donation")
@app_commands.autocomplete(name=name_autocomplete)
@app_commands.checks.has_permissions(manage_guild=True)
async def add(interaction: discord.Interaction, name: str, amount: float, donor: str = None):
    if not get_campaign(interaction.guild_id, name):
        return await interaction.response.send_message(
            f"No campaign named **{name}**.", ephemeral=True)

    db.execute(
        "INSERT INTO donation (guild_id, name, amount, donor, ts) VALUES (?,?,?,?,?)",
        (interaction.guild_id, name, amount, donor,
         datetime.now(timezone.utc).isoformat()))
    db.commit()

    await refresh_board(interaction.guild, name)
    await respond_with(interaction, name)


@fund.command(name="show", description="Show current progress")
@app_commands.autocomplete(name=name_autocomplete)
async def show(interaction: discord.Interaction, name: str):
    if not get_campaign(interaction.guild_id, name):
        return await interaction.response.send_message(
            f"No campaign named **{name}**.", ephemeral=True)
    await respond_with(interaction, name)


@fund.command(name="list", description="List every active fundraiser")
async def list_cmd(interaction: discord.Interaction):
    rows = db.execute(
        "SELECT name, goal, currency, link FROM campaign WHERE guild_id=? ORDER BY name",
        (interaction.guild_id,)).fetchall()

    if not rows:
        return await interaction.response.send_message(
            "No campaigns yet. Start one with `/fund create`.", ephemeral=True)

    e = discord.Embed(
        title="\U0001F4CB Active fundraisers",
        colour=discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )

    grand_raised = grand_goal = 0.0
    for name, goal, cur, link in rows:
        raised, count = totals(interaction.guild_id, name)
        grand_raised += raised
        grand_goal += goal
        pct = raised / goal if goal else 0.0

        value = (f"`{bar(pct, 16)}` **{pct * 100:.0f}%**\n"
                 f"{cur}{raised:,.2f} of {cur}{goal:,.2f} \u00b7 "
                 f"{count} gift{'s' if count != 1 else ''}")
        if valid_link(link):
            value += f" \u00b7 [Donate]({link})"

        e.add_field(name=("\u2705 " if pct >= 1 else "") + name, value=value, inline=False)

    e.set_footer(text=f"{len(rows)} campaign{'s' if len(rows) != 1 else ''} \u00b7 "
                      f"{grand_raised:,.2f} of {grand_goal:,.2f} overall")

    # Button uses the shared default link, since campaigns may differ.
    await interaction.response.send_message(embed=e, view=donate_view(DONATE_URL))


@fund.command(name="board", description="Post a live-updating tracker in this channel")
@app_commands.autocomplete(name=name_autocomplete)
@app_commands.checks.has_permissions(manage_guild=True)
async def board(interaction: discord.Interaction, name: str):
    if not get_campaign(interaction.guild_id, name):
        return await interaction.response.send_message(
            f"No campaign named **{name}**.", ephemeral=True)

    await respond_with(interaction, name)
    msg = await interaction.original_response()
    try:
        await msg.pin()
    except discord.Forbidden:
        pass

    db.execute(
        "UPDATE campaign SET channel_id=?, message_id=? WHERE guild_id=? AND name=?",
        (interaction.channel_id, msg.id, interaction.guild_id, name))
    db.commit()


@fund.command(name="undo", description="Remove the most recent donation")
@app_commands.autocomplete(name=name_autocomplete)
@app_commands.checks.has_permissions(manage_guild=True)
async def undo(interaction: discord.Interaction, name: str):
    row = db.execute(
        "SELECT id, amount FROM donation WHERE guild_id=? AND name=? ORDER BY id DESC LIMIT 1",
        (interaction.guild_id, name)).fetchone()
    if not row:
        return await interaction.response.send_message("Nothing to undo.", ephemeral=True)

    db.execute("DELETE FROM donation WHERE id=?", (row[0],))
    db.commit()
    await refresh_board(interaction.guild, name)
    await interaction.response.send_message(
        f"Removed last donation of {row[1]:,.2f}.", ephemeral=True)


bot.tree.add_command(fund)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        msg = "You don't have permission to use that."
    else:
        msg = "That didn't go through. Check the container log for details."
        print(f"[command error] {error!r}")

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# ---------- lifecycle ----------

_synced = False


@bot.event
async def setup_hook():
    await webserver.start(db, totals, port=WEB_PORT,
                          static_dir=STATIC_DIR, show_donors=SHOW_DONORS)
    print(f"Web sheet listening on :{WEB_PORT}")


@bot.event
async def on_ready():
    global _synced
    if not _synced:
        if GUILD_ID:
            g = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=g)
            await bot.tree.sync(guild=g)
        else:
            await bot.tree.sync()
        _synced = True
    print(f"Logged in as {bot.user} ({len(bot.guilds)} guild(s))")


def wait_for_dns(host: str = "discord.com", timeout: float = 300) -> None:
    """Block until DNS resolves.

    On Unraid this container can start before the router/AdGuard finishes
    booting; login() raising here kills the whole process (bot + web sheet)
    with no restart policy applied. Retry with backoff instead of failing fast.
    """
    deadline = time.monotonic() + timeout
    delay = 1
    while True:
        try:
            socket.getaddrinfo(host, 443)
            return
        except socket.gaierror:
            if time.monotonic() >= deadline:
                print(f"[startup] DNS still unresolved for {host} after {timeout:.0f}s, trying anyway")
                return
            print(f"[startup] DNS not ready ({host}), retrying in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 30)


wait_for_dns()
bot.run(TOKEN)
