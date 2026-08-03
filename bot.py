#!/usr/bin/env python3
"""
Discord fundraising tracker.

Env:
  DISCORD_TOKEN  (required)  bot token
  DB_PATH        (optional)  default /data/fundraiser.db
  GUILD_ID       (optional)  numeric guild id -> instant slash-command sync
"""

import os
import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.environ["DISCORD_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "/data/fundraiser.db")
GUILD_ID = os.environ.get("GUILD_ID")

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
db.commit()

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())


# ---------- data helpers ----------

def get_campaign(guild_id: int, name: str):
    return db.execute(
        "SELECT name, goal, currency, channel_id, message_id "
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
    return "█" * filled + "░" * (width - filled)


def build_embed(guild_id: int, name: str) -> discord.Embed:
    _, goal, cur, _, _ = get_campaign(guild_id, name)
    raised, count = totals(guild_id, name)
    pct = raised / goal if goal else 0.0

    e = discord.Embed(
        title=f"🎯 {name}",
        description=f"`{bar(pct)}`  **{pct * 100:.1f}%**",
        colour=discord.Colour.green() if pct >= 1 else discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    e.add_field(name="Raised", value=f"{cur}{raised:,.2f}")
    e.add_field(name="Goal", value=f"{cur}{goal:,.2f}")
    e.add_field(name="Remaining", value=f"{cur}{max(0.0, goal - raised):,.2f}")
    e.set_footer(text=f"{count} donation{'s' if count != 1 else ''} · updated")

    recent = db.execute(
        "SELECT donor, amount FROM donation WHERE guild_id=? AND name=? "
        "ORDER BY id DESC LIMIT 5", (guild_id, name)
    ).fetchall()
    if recent:
        e.add_field(
            name="Recent",
            value="\n".join(f"{d or 'Anonymous'} — {cur}{a:,.2f}" for d, a in recent),
            inline=False,
        )
    return e


async def refresh_board(guild: discord.Guild, name: str):
    """Edit the pinned tracker message, if one exists."""
    row = get_campaign(guild.id, name)
    if not row or not row[3] or not row[4]:
        return
    channel = guild.get_channel(row[3])
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(row[4])
        await msg.edit(embed=build_embed(guild.id, name))
    except (discord.NotFound, discord.Forbidden):
        db.execute(
            "UPDATE campaign SET channel_id=NULL, message_id=NULL "
            "WHERE guild_id=? AND name=?", (guild.id, name))
        db.commit()


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
async def create(interaction: discord.Interaction, name: str, goal: float, currency: str = "$"):
    db.execute(
        "INSERT INTO campaign (guild_id, name, goal, currency) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id, name) DO UPDATE SET goal=excluded.goal, currency=excluded.currency",
        (interaction.guild_id, name, goal, currency))
    db.commit()
    await refresh_board(interaction.guild, name)
    await interaction.response.send_message(
        f"Campaign **{name}** set to {currency}{goal:,.2f}.", ephemeral=True)


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
    await interaction.response.send_message(embed=build_embed(interaction.guild_id, name))


@fund.command(name="show", description="Show current progress")
@app_commands.autocomplete(name=name_autocomplete)
async def show(interaction: discord.Interaction, name: str):
    if not get_campaign(interaction.guild_id, name):
        return await interaction.response.send_message(
            f"No campaign named **{name}**.", ephemeral=True)
    await interaction.response.send_message(embed=build_embed(interaction.guild_id, name))


@fund.command(name="board", description="Post a live-updating tracker in this channel")
@app_commands.autocomplete(name=name_autocomplete)
@app_commands.checks.has_permissions(manage_guild=True)
async def board(interaction: discord.Interaction, name: str):
    if not get_campaign(interaction.guild_id, name):
        return await interaction.response.send_message(
            f"No campaign named **{name}**.", ephemeral=True)

    await interaction.response.send_message(embed=build_embed(interaction.guild_id, name))
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


@bot.event
async def on_ready():
    if GUILD_ID:
        g = discord.Object(id=int(GUILD_ID))
        bot.tree.copy_global_to(guild=g)
        await bot.tree.sync(guild=g)
    else:
        await bot.tree.sync()
    print(f"Logged in as {bot.user} ({len(bot.guilds)} guild(s))")


bot.run(TOKEN)
