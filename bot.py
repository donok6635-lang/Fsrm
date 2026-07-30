"""
FarmBot — Discord Member Farming Bot
─────────────────────────────────────────────────────────
Prefix commands:  !help, !lauth, !addbot, !authbot, !farm, !tutorial …
Slash commands:   /help, /lauth, /addbot, /authbot, /farm, /tutorial …
Owner commands:   !ownerhelp / /ownerhelp
Embed editor:     !editembed / /editembed  (owner only)
─────────────────────────────────────────────────────────
"""

import asyncio
import os
import sys
import urllib.parse
from datetime import datetime

import aiohttp
import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    BOT_TOKEN, CLIENT_ID, REDIRECT_URI,
    OWNER_ID, ROLE_TIERS, DISCORD_API,
)
import database as db

# ──────────────────────────────────────────────────────────────────────────
#  Embed registry — keys must match DB and EMBED_CHOICES below
# ──────────────────────────────────────────────────────────────────────────

EMBED_DEFAULTS: dict[str, dict] = {
    "lauth": {
        "title": "🔐 FarmBot Authorization",
        "description": (
            "Use the buttons below to get started:\n\n"
            "🤖 **add-bot** — Add FarmBot to your server\n"
            "🔑 **auth-bot** — Authorize yourself to be farmed"
        ),
        "color": 0x5865F2,
        "footer": "FarmBot • Click a button to continue",
    },
    "addbot": {
        "title": "🤖 Add Bot to Your Server",
        "description": (
            "Click the link below to invite FarmBot:\n"
            "**[→ Invite FarmBot]({invite_url})**\n\n"
            "The bot requires **Administrator** permission.\n"
            "After adding, ask the owner to whitelist your server: `!grantserver <id>`"
        ),
        "color": 0x5865F2,
        "footer": "FarmBot • Bot Invite",
    },
    "authbot": {
        "title": "🔑 Authorize FarmBot",
        "description": (
            "Click below to authorize yourself:\n"
            "**[→ Authorize Now]({oauth_url})**\n\n"
            "This allows FarmBot to add you to servers.\n"
            "Your data is kept private and secure."
        ),
        "color": 0x57F287,
        "footer": "FarmBot • OAuth2 Authorization",
    },
    "farm_success": {
        "title": "🌾 Farm Complete!",
        "description": "Members successfully added.",
        "color": 0x57F287,
        "footer": "FarmBot • Farm Log",
    },
    "farm_fail": {
        "title": "❌ Farm Failed",
        "description": "No members could be added. Tokens may be expired.",
        "color": 0xED4245,
        "footer": "FarmBot",
    },
    "help": {
        "title": "📋 FarmBot Help",
        "description": "All commands are available as both `!prefix` and `/slash` commands.",
        "color": 0x5865F2,
        "footer": "FarmBot • Use !ownerhelp for admin commands",
    },
    "tutorial": {
        "title": "📖 Tutorial",
        "description": "How to use FarmBot.",
        "color": 0xFEE75C,
        "footer": "FarmBot • Tutorial",
    },
}

EMBED_CHOICES = [
    ("Auth Embed  (!lauth main)", "lauth"),
    ("Add-Bot Response", "addbot"),
    ("Auth-Bot Response", "authbot"),
    ("Farm Success", "farm_success"),
    ("Farm Failed", "farm_fail"),
    ("Help Embed", "help"),
    ("Tutorial Header", "tutorial"),
]


async def build_embed(name: str, **format_vars) -> discord.Embed:
    """Load embed from DB (owner-edited) falling back to EMBED_DEFAULTS."""
    stored = await db.get_custom_embed(name)
    defs = EMBED_DEFAULTS.get(name, {})

    title = (stored.get("title") if stored else None) or defs.get("title", "")
    desc  = (stored.get("description") if stored else None) or defs.get("description", "")
    color = (stored.get("color") if stored else None) or defs.get("color", 0x5865F2)
    footer = (stored.get("footer") if stored else None) or defs.get("footer", "FarmBot")

    if format_vars:
        try:
            desc = desc.format(**format_vars)
        except (KeyError, ValueError):
            pass

    e = discord.Embed(title=title or None, description=desc or None, color=color)
    if footer:
        e.set_footer(text=footer)
    return e


# ──────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def owner_only():
    async def predicate(ctx: commands.Context) -> bool:
        if not is_owner(ctx.author.id):
            await ctx.send(embed=discord.Embed(
                description="❌ Owner only command.", color=0xED4245))
            return False
        return True
    return commands.check(predicate)


def owner_slash_check(interaction: discord.Interaction) -> bool:
    return is_owner(interaction.user.id)


def get_user_tier(member: discord.Member) -> str:
    names = {r.name.lower() for r in member.roles}
    for t in ("premium", "diamond", "gold", "silver", "member"):
        if t in names:
            return t
    return "member"


def get_farm_limit(member: discord.Member) -> int:
    return ROLE_TIERS.get(get_user_tier(member), 2)


def err_e(desc: str) -> discord.Embed:
    return discord.Embed(description=desc, color=0xED4245)


def ok_e(title: str, desc: str = "") -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=0x57F287)
    e.set_footer(text="FarmBot")
    return e


def info_e(title: str, desc: str = "") -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=0x5865F2)
    e.set_footer(text="FarmBot")
    return e


def make_invite_url() -> str:
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands"
    )


def make_oauth_url(user_id: int) -> str | None:
    redirect = os.getenv("REDIRECT_URI", REDIRECT_URI)
    if not redirect:
        return None
    enc = urllib.parse.quote(redirect, safe="")
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={enc}"
        f"&response_type=code"
        f"&scope=identify%20guilds.join"
        f"&state={user_id}"
    )


# ──────────────────────────────────────────────────────────────────────────
#  Views
# ──────────────────────────────────────────────────────────────────────────

class AuthView(ui.View):
    """Persistent view — shown by !lauth / /lauth."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="add-bot", style=discord.ButtonStyle.primary,
               emoji="🤖", custom_id="farm:add_bot")
    async def add_bot(self, interaction: discord.Interaction, _btn: ui.Button):
        invite = make_invite_url()
        e = await build_embed("addbot", invite_url=invite)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @ui.button(label="auth-bot", style=discord.ButtonStyle.success,
               emoji="🔑", custom_id="farm:auth_bot")
    async def auth_bot(self, interaction: discord.Interaction, _btn: ui.Button):
        oauth = make_oauth_url(interaction.user.id)
        if not oauth:
            await interaction.response.send_message(
                embed=err_e("❌ Redirect URI not set yet. Ask the owner."), ephemeral=True)
            return
        e = await build_embed("authbot", oauth_url=oauth)
        await interaction.response.send_message(embed=e, ephemeral=True)


class MsgEditModal(ui.Modal, title="Edit Bot Message"):
    """Modal for editing content + embed of a specific sent message."""
    def __init__(self, message: discord.Message):
        super().__init__()
        self.target_msg = message

        existing_content = message.content or ""
        existing_embed   = message.embeds[0] if message.embeds else None

        self.f_content = ui.TextInput(
            label="Message text (leave blank to keep)",
            style=discord.TextStyle.paragraph,
            default=existing_content[:4000] if existing_content else "",
            required=False,
            max_length=2000,
        )
        self.f_title = ui.TextInput(
            label="Embed title (leave blank to keep)",
            default=(existing_embed.title or "")[:100] if existing_embed else "",
            required=False,
            max_length=256,
        )
        self.f_desc = ui.TextInput(
            label="Embed description (leave blank to keep)",
            style=discord.TextStyle.paragraph,
            default=(existing_embed.description or "")[:4000] if existing_embed else "",
            required=False,
            max_length=4000,
        )
        self.f_color = ui.TextInput(
            label="Embed color hex (e.g. #5865F2)",
            default=(f"#{existing_embed.color.value:06X}" if existing_embed and existing_embed.color else "#5865F2"),
            required=False,
            max_length=10,
        )
        self.f_footer = ui.TextInput(
            label="Embed footer (leave blank to keep)",
            default=(existing_embed.footer.text or "")[:200] if (existing_embed and existing_embed.footer) else "",
            required=False,
            max_length=200,
        )
        self.add_item(self.f_content)
        self.add_item(self.f_title)
        self.add_item(self.f_desc)
        self.add_item(self.f_color)
        self.add_item(self.f_footer)

    async def on_submit(self, interaction: discord.Interaction):
        new_content = self.f_content.value or None
        existing_embed = self.target_msg.embeds[0] if self.target_msg.embeds else None

        new_embed = discord.utils.MISSING
        # Only build a new embed if any embed field was filled OR there was already an embed
        if existing_embed or any([self.f_title.value, self.f_desc.value, self.f_footer.value]):
            raw_hex = self.f_color.value.strip().lstrip("#") or "5865F2"
            try:
                color_int = int(raw_hex[:6], 16)
            except ValueError:
                color_int = 0x5865F2

            new_embed = discord.Embed(
                title=self.f_title.value or (existing_embed.title if existing_embed else None),
                description=self.f_desc.value or (existing_embed.description if existing_embed else None),
                color=color_int,
            )
            footer_text = self.f_footer.value or (existing_embed.footer.text if (existing_embed and existing_embed.footer) else None)
            if footer_text:
                new_embed.set_footer(text=footer_text)

        try:
            kwargs = {}
            if new_content is not None:
                kwargs["content"] = new_content
            if new_embed is not discord.utils.MISSING:
                kwargs["embed"] = new_embed
            await self.target_msg.edit(**kwargs)
            await interaction.response.send_message(
                embed=ok_e("✅ Message Updated", f"[Jump to message]({self.target_msg.jump_url})"),
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=err_e("❌ I can't edit that message (not mine or missing permissions)."), ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(embed=err_e(f"❌ Edit failed: {exc}"), ephemeral=True)


class EmbedSelectView(ui.View):
    """Owner dropdown to pick which embed to edit."""
    def __init__(self):
        super().__init__(timeout=60)

    @ui.select(
        placeholder="Choose which embed to edit…",
        options=[
            discord.SelectOption(label=label, value=key, emoji="✏️")
            for label, key in EMBED_CHOICES
        ],
    )
    async def pick_embed(self, interaction: discord.Interaction, select: ui.Select):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
            return
        key = select.values[0]
        stored = await db.get_custom_embed(key) or {}
        defs   = EMBED_DEFAULTS.get(key, {})
        await interaction.response.send_modal(EmbedEditModal(key, stored, defs))


class EmbedEditModal(ui.Modal):
    def __init__(self, key: str, stored: dict, defs: dict):
        label_map = {v: l for l, v in EMBED_CHOICES}
        super().__init__(title=f"Edit: {label_map.get(key, key)}")
        self.embed_key = key

        cur_title  = stored.get("title")  or defs.get("title",  "")
        cur_desc   = stored.get("description") or defs.get("description", "")
        cur_color  = stored.get("color_hex") or f"#{defs.get('color', 0x5865F2):06X}"
        cur_footer = stored.get("footer") or defs.get("footer", "FarmBot")

        self.f_title = ui.TextInput(
            label="Title",
            default=cur_title[:100] if cur_title else "",
            required=False,
            max_length=256,
        )
        self.f_desc = ui.TextInput(
            label="Description  (use {invite_url} or {oauth_url} if needed)",
            style=discord.TextStyle.paragraph,
            default=cur_desc[:4000] if cur_desc else "",
            required=False,
            max_length=4000,
        )
        self.f_color = ui.TextInput(
            label="Color (hex, e.g. #5865F2)",
            default=cur_color,
            required=False,
            max_length=10,
        )
        self.f_footer = ui.TextInput(
            label="Footer text",
            default=cur_footer[:200] if cur_footer else "FarmBot",
            required=False,
            max_length=200,
        )
        self.add_item(self.f_title)
        self.add_item(self.f_desc)
        self.add_item(self.f_color)
        self.add_item(self.f_footer)

    async def on_submit(self, interaction: discord.Interaction):
        raw_hex = self.f_color.value.strip().lstrip("#") or "5865F2"
        try:
            color_int = int(raw_hex[:6], 16)
        except ValueError:
            color_int = 0x5865F2

        await db.set_custom_embed(self.embed_key, {
            "title":       self.f_title.value,
            "description": self.f_desc.value,
            "color":       color_int,
            "color_hex":   f"#{raw_hex[:6].upper()}",
            "footer":      self.f_footer.value,
        })
        # Preview
        e = await build_embed(self.embed_key)
        await interaction.response.send_message(
            content=f"✅ Embed **`{self.embed_key}`** updated! Preview:",
            embed=e,
            ephemeral=True,
        )


# ──────────────────────────────────────────────────────────────────────────
#  Bot + Tree
# ──────────────────────────────────────────────────────────────────────────

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    await db.init_db()
    bot.add_view(AuthView())
    process_pending.start()

    # Sync slash commands globally
    try:
        synced = await bot.tree.sync()
        print(f"✅  Logged in as {bot.user} ({bot.user.id})")
        print(f"⚡  Synced {len(synced)} slash command(s) globally")
    except Exception as ex:
        print(f"⚠️  Slash sync error: {ex}")

    redirect = os.getenv("REDIRECT_URI", REDIRECT_URI)
    if redirect:
        print(f"🔗  Redirect URI: {redirect}")
    else:
        domain = os.getenv("REPLIT_DEV_DOMAIN", "")
        if domain:
            print(f"⚠️  Set REDIRECT_URI to: https://{domain}/api/auth/callback")


@tasks.loop(seconds=10)
async def process_pending():
    try:
        n = await db.process_pending_auth()
        if n:
            print(f"[auth] processed {n} pending auth(s)")
    except Exception as exc:
        print(f"[auth] pending error: {exc}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SHARED LOGIC (called by both prefix and slash variants)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _send(ctx_or_interaction, **kwargs):
    """Unified send for both Context and Interaction."""
    if isinstance(ctx_or_interaction, discord.Interaction):
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(**kwargs)
        else:
            await ctx_or_interaction.response.send_message(**kwargs)
    else:
        await ctx_or_interaction.send(**kwargs)


async def _get_member(ctx_or_interaction) -> discord.Member | None:
    if isinstance(ctx_or_interaction, discord.Interaction):
        return ctx_or_interaction.guild.get_member(ctx_or_interaction.user.id) if ctx_or_interaction.guild else None
    return ctx_or_interaction.author if ctx_or_interaction.guild else None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GENERAL — PREFIX COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.command(name="ping")
async def cmd_ping(ctx: commands.Context):
    await ctx.send(embed=ok_e("🏓 Pong!", f"Latency: **{round(bot.latency*1000)}ms**"))


@bot.command(name="help")
async def cmd_help(ctx: commands.Context):
    e = await build_embed("help")
    e.add_field(name="🔑 Auth & Setup", value=(
        "`!lauth` / `/lauth` — Auth embed with buttons\n"
        "`!addbot` / `/addbot` — Get bot invite link\n"
        "`!authbot` / `/authbot` — Authorize yourself\n"
        "`!myauth` / `/myauth` — Your auth status\n"
        "`!authcount` / `/authcount` — Authorized user count"
    ), inline=False)
    e.add_field(name="🌾 Farming", value=(
        "`!farm <server_id>` / `/farm` — Add members\n"
        "`!farmstats` / `/farmstats` — Your farm history\n"
        "`!roles` / `/roles` — Role tier limits\n"
        "`!tutorial` / `/tutorial` — How-to guide"
    ), inline=False)
    e.add_field(name="⚙️ Roles (requires Manage Roles)", value=(
        "`!giverole @user <role>` / `/giverole`\n"
        "`!removerole @user <role>` / `/removerole`"
    ), inline=False)
    e.add_field(name="👑 Owner", value="`!ownerhelp` / `/ownerhelp` — Owner command list", inline=False)
    await ctx.send(embed=e)


@bot.command(name="lauth")
async def cmd_lauth(ctx: commands.Context):
    e = await build_embed("lauth")
    e.add_field(
        name="📊 Role Tiers",
        value="\n".join(f"• `{t.capitalize()}` — {l} members / !farm" for t, l in ROLE_TIERS.items()),
        inline=False,
    )
    await ctx.send(embed=e, view=AuthView())


@bot.command(name="addbot")
async def cmd_addbot(ctx: commands.Context):
    """Separate !addbot command — just the invite link embed."""
    invite = make_invite_url()
    e = await build_embed("addbot", invite_url=invite)
    await ctx.send(embed=e)


@bot.command(name="authbot")
async def cmd_authbot(ctx: commands.Context):
    """Separate !authbot command — just the OAuth2 auth link embed."""
    oauth = make_oauth_url(ctx.author.id)
    if not oauth:
        await ctx.send(embed=err_e("❌ Redirect URI not configured. Ask the owner."))
        return
    e = await build_embed("authbot", oauth_url=oauth)
    await ctx.send(embed=e)


@bot.command(name="tutorial")
async def cmd_tutorial(ctx: commands.Context):
    text = await db.get_config("tutorial")
    e = await build_embed("tutorial")
    e.description = text or e.description
    await ctx.send(embed=e)


@bot.command(name="myauth")
async def cmd_myauth(ctx: commands.Context):
    user = await db.get_authorized_user(str(ctx.author.id))
    has_access = await db.has_user_access(str(ctx.author.id))
    if user:
        ts  = datetime.fromtimestamp(user["authorized_at"]).strftime("%Y-%m-%d %H:%M")
        exp = datetime.fromtimestamp(user["token_expires"]).strftime("%Y-%m-%d %H:%M")
        e = ok_e("✅ You are authorized!", f"Authorized: `{ts}`\nToken expires: `{exp}`")
        e.add_field(name="🌾 Farm Access", value="✅ Yes" if (has_access or is_owner(ctx.author.id)) else "❌ No", inline=True)
        if ctx.guild:
            tier = get_user_tier(ctx.author)
            e.add_field(name="🏷️ Tier", value=f"`{tier.capitalize()}`", inline=True)
            e.add_field(name="⚡ Limit", value=f"{ROLE_TIERS.get(tier,2)} / cmd", inline=True)
    else:
        e = err_e("❌ Not authorized. Use `!authbot` or click **auth-bot** in `!lauth`.")
    await ctx.send(embed=e)


@bot.command(name="authcount")
async def cmd_authcount(ctx: commands.Context):
    total = await db.count_authorized()
    gs = await db.global_farm_stats()
    e = info_e("📊 Stats", f"**Authorized Users:** `{total}`\n**Farm Runs:** `{gs['runs']}`\n**Members Added:** `{gs['total']}`")
    await ctx.send(embed=e)


@bot.command(name="roles")
async def cmd_roles(ctx: commands.Context):
    e = info_e("🏷️ Role Tiers", "\n".join(f"• `{t.capitalize()}` — **{l}** members / `!farm`" for t, l in ROLE_TIERS.items()))
    e.set_footer(text="Ask an admin to assign your role")
    await ctx.send(embed=e)


@bot.command(name="farmstats")
async def cmd_farmstats(ctx: commands.Context):
    stats = await db.get_farm_stats(str(ctx.author.id))
    tier  = get_user_tier(ctx.author) if ctx.guild else "unknown"
    e = info_e(f"🌾 Farm Stats — {ctx.author.display_name}",
               f"**Runs:** `{stats['times']}`\n**Members Added:** `{stats['total']}`\n"
               f"**Tier:** `{tier.capitalize()}`\n**Limit:** `{ROLE_TIERS.get(tier,2)}` / cmd")
    await ctx.send(embed=e)


@bot.command(name="editembed")
@owner_only()
async def cmd_editembed(ctx: commands.Context):
    e = info_e("✏️ Edit Embed", "Select which embed you want to edit from the dropdown below.")
    await ctx.send(embed=e, view=EmbedSelectView())


@bot.command(name="editmsg")
@owner_only()
async def cmd_editmsg(ctx: commands.Context, message_id: str = "", channel_id: str = ""):
    """Edit a specific message the bot sent. Usage: !editmsg <message_id> [channel_id]"""
    if not message_id:
        await ctx.send(embed=err_e(
            "Usage: `!editmsg <message_id>` — edits a message in this channel\n"
            "Or: `!editmsg <message_id> <channel_id>` — edits a message in another channel"
        ))
        return
    try:
        ch = ctx.channel if not channel_id else bot.get_channel(int(channel_id))
        if ch is None:
            await ctx.send(embed=err_e(f"❌ Channel `{channel_id}` not found."))
            return
        msg = await ch.fetch_message(int(message_id))
    except discord.NotFound:
        await ctx.send(embed=err_e(f"❌ Message `{message_id}` not found."))
        return
    except ValueError:
        await ctx.send(embed=err_e("❌ Invalid message or channel ID."))
        return
    if msg.author.id != bot.user.id:
        await ctx.send(embed=err_e("❌ That message wasn't sent by me."))
        return
    # Prefix commands can't open modals — send a link + instructions
    await ctx.send(
        embed=info_e(
            "✏️ Edit Message",
            f"Use the slash command `/editmsg` with message ID `{message_id}` to open the edit form.\n\n"
            f"[Jump to message]({msg.jump_url})"
        )
    )


# ── FARM (prefix) ──────────────────────────────────────────────────────────

@bot.command(name="farm")
async def cmd_farm(ctx: commands.Context, server_id: str = ""):
    if not server_id:
        await ctx.send(embed=err_e("Usage: `!farm <server_id>`"))
        return
    await _do_farm(ctx, server_id)


async def _do_farm(dest, server_id: str):
    """Shared farm logic for prefix + slash."""
    is_interaction = isinstance(dest, discord.Interaction)
    author = dest.user if is_interaction else dest.author
    guild  = dest.guild if is_interaction else dest.guild

    owner = is_owner(author.id)
    if not owner and not await db.has_user_access(str(author.id)):
        await _send(dest, embed=err_e("❌ You don't have farm access. Ask the owner for `!giveaccess`."))
        return
    if not await db.has_server_access(server_id):
        await _send(dest, embed=err_e(f"❌ Server `{server_id}` is not whitelisted. Owner: `!grantserver {server_id}`"))
        return
    try:
        target = bot.get_guild(int(server_id))
    except ValueError:
        await _send(dest, embed=err_e("❌ Invalid server ID."))
        return
    if not target:
        await _send(dest, embed=err_e(f"❌ I'm not in server `{server_id}`. Add me first via `!addbot`."))
        return

    member = guild.get_member(author.id) if guild else None
    tier   = get_user_tier(member) if member else "member"
    limit  = ROLE_TIERS.get(tier, 2) if not owner else 9999

    all_auth = await db.get_all_authorized(limit=limit * 3)
    candidates = [u for u in all_auth if u["user_id"] != str(author.id)][:limit]

    if not candidates:
        await _send(dest, embed=err_e("❌ No authorized users to farm. They need to use `!authbot` first."))
        return

    if is_interaction:
        await dest.response.send_message(
            embed=info_e("🌾 Farming…", f"Adding up to **{len(candidates)}** members to `{target.name}`…"))
    else:
        msg = await dest.send(embed=info_e("🌾 Farming…", f"Adding up to **{len(candidates)}** members to `{target.name}`…"))

    added = failed = 0
    async with aiohttp.ClientSession() as session:
        for u in candidates:
            try:
                url = f"{DISCORD_API}/guilds/{server_id}/members/{u['user_id']}"
                headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
                async with session.put(url, json={"access_token": u["access_token"]}, headers=headers) as r:
                    if r.status in (201, 204):
                        added += 1
                    else:
                        failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.5)

    await db.log_farm(str(author.id), server_id, added, tier)

    result = await build_embed("farm_success") if added > 0 else await build_embed("farm_fail")
    result.description = (
        f"**Server:** {target.name} (`{server_id}`)\n"
        f"**Added:** `{added}` ✅   **Failed:** `{failed}` ❌\n"
        f"**Tier:** `{tier.capitalize()}` (limit: {limit})"
    )
    if is_interaction:
        await dest.followup.send(embed=result)
    else:
        await msg.edit(embed=result)


# ── ROLE MANAGEMENT (prefix) ───────────────────────────────────────────────

@bot.command(name="giverole")
@commands.has_permissions(manage_roles=True)
async def cmd_giverole(ctx: commands.Context, member: discord.Member = None, *, role_name: str = ""):
    if not member or not role_name:
        await ctx.send(embed=err_e("Usage: `!giverole @user <role_name>`"))
        return
    role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
    if not role:
        await ctx.send(embed=err_e(f"Role `{role_name}` not found."))
        return
    if role >= ctx.guild.me.top_role:
        await ctx.send(embed=err_e("❌ That role is above my highest role."))
        return
    await member.add_roles(role, reason=f"Assigned by {ctx.author}")
    await ctx.send(embed=ok_e("✅ Role Assigned", f"Gave **{role.name}** to {member.mention}."))


@bot.command(name="removerole")
@commands.has_permissions(manage_roles=True)
async def cmd_removerole(ctx: commands.Context, member: discord.Member = None, *, role_name: str = ""):
    if not member or not role_name:
        await ctx.send(embed=err_e("Usage: `!removerole @user <role_name>`"))
        return
    role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
    if not role:
        await ctx.send(embed=err_e(f"Role `{role_name}` not found."))
        return
    if role not in member.roles:
        await ctx.send(embed=err_e(f"{member.mention} doesn't have `{role.name}`."))
        return
    await member.remove_roles(role, reason=f"Removed by {ctx.author}")
    await ctx.send(embed=ok_e("✅ Role Removed", f"Removed **{role.name}** from {member.mention}."))


# ── OWNER COMMANDS (prefix) ────────────────────────────────────────────────

@bot.command(name="ownerhelp")
@owner_only()
async def cmd_ownerhelp(ctx: commands.Context):
    e = discord.Embed(title="👑 Owner Commands", color=0xF1C40F)
    e.add_field(name="🔓 Access", value=(
        "`!giveaccess <id>` — Grant farm access\n"
        "`!removeaccess <id>` — Revoke farm access\n"
        "`!listusers` — Users with access\n"
        "`!clearauth <id>` — Delete OAuth token"
    ), inline=False)
    e.add_field(name="🏠 Servers", value=(
        "`!grantserver <id>` — Whitelist server\n"
        "`!revokeserver <id>` — Remove whitelist\n"
        "`!listservers` — All whitelisted servers\n"
        "`!serverinfo <id>` — Server info"
    ), inline=False)
    e.add_field(name="📊 Management", value=(
        "`!resetfarm <id>` — Reset farm stats\n"
        "`!announce <msg>` — DM all authorized users\n"
        "`!botinfo` — Bot statistics"
    ), inline=False)
    e.add_field(name="✏️ Embeds & Config", value=(
        "`!editembed` — Edit any bot embed template (dropdown)\n"
        "`!settutorial <text>` — Edit tutorial text\n"
        "`/editmsg <message_id>` — Edit a specific message the bot sent"
    ), inline=False)
    e.set_footer(text="All owner commands also available as /slash commands")
    await ctx.send(embed=e)


@bot.command(name="giveaccess")
@owner_only()
async def cmd_giveaccess(ctx: commands.Context, user_id: str = ""):
    if not user_id:
        await ctx.send(embed=err_e("Usage: `!giveaccess <user_id>`"))
        return
    await db.grant_user_access(user_id, str(ctx.author.id))
    await ctx.send(embed=ok_e("✅ Access Granted", f"User `{user_id}` can now use `!farm`."))


@bot.command(name="removeaccess")
@owner_only()
async def cmd_removeaccess(ctx: commands.Context, user_id: str = ""):
    if not user_id:
        await ctx.send(embed=err_e("Usage: `!removeaccess <user_id>`"))
        return
    ok = await db.revoke_user_access(user_id)
    msg = f"Revoked access from `{user_id}`." if ok else f"`{user_id}` had no access."
    await ctx.send(embed=(ok_e("✅ Done", msg) if ok else err_e(msg)))


@bot.command(name="grantserver")
@owner_only()
async def cmd_grantserver(ctx: commands.Context, server_id: str = ""):
    if not server_id:
        await ctx.send(embed=err_e("Usage: `!grantserver <server_id>`"))
        return
    await db.grant_server_access(server_id, str(ctx.author.id))
    g = bot.get_guild(int(server_id))
    name = g.name if g else "Unknown"
    await ctx.send(embed=ok_e("✅ Server Whitelisted", f"`{server_id}` ({name}) approved."))


@bot.command(name="revokeserver")
@owner_only()
async def cmd_revokeserver(ctx: commands.Context, server_id: str = ""):
    if not server_id:
        await ctx.send(embed=err_e("Usage: `!revokeserver <server_id>`"))
        return
    ok = await db.revoke_server_access(server_id)
    await ctx.send(embed=(ok_e("✅ Removed", f"`{server_id}` removed.") if ok else err_e(f"`{server_id}` was not listed.")))


@bot.command(name="listservers")
@owner_only()
async def cmd_listservers(ctx: commands.Context):
    rows = await db.list_server_access()
    if not rows:
        await ctx.send(embed=info_e("📋 Whitelisted Servers", "None yet."))
        return
    lines = []
    for r in rows:
        g = bot.get_guild(int(r["server_id"]))
        ts = datetime.fromtimestamp(r["granted_at"]).strftime("%Y-%m-%d")
        lines.append(f"`{r['server_id']}` — **{g.name if g else 'Unknown'}** ({ts})")
    e = info_e("📋 Whitelisted Servers", "\n".join(lines[:20]))
    e.set_footer(text=f"{len(rows)} total")
    await ctx.send(embed=e)


@bot.command(name="listusers")
@owner_only()
async def cmd_listusers(ctx: commands.Context):
    rows = await db.list_user_access()
    if not rows:
        await ctx.send(embed=info_e("📋 Farm Access Users", "None yet."))
        return
    lines = [f"`{r['user_id']}` — by `{r['granted_by']}` on {datetime.fromtimestamp(r['granted_at']).strftime('%Y-%m-%d')}" for r in rows[:20]]
    e = info_e("📋 Farm Access Users", "\n".join(lines))
    e.set_footer(text=f"{len(rows)} total")
    await ctx.send(embed=e)


@bot.command(name="clearauth")
@owner_only()
async def cmd_clearauth(ctx: commands.Context, user_id: str = ""):
    if not user_id:
        await ctx.send(embed=err_e("Usage: `!clearauth <user_id>`"))
        return
    ok = await db.delete_authorized_user(user_id)
    await ctx.send(embed=(ok_e("✅ Cleared", f"Removed OAuth token for `{user_id}`.") if ok else err_e(f"`{user_id}` not found.")))


@bot.command(name="resetfarm")
@owner_only()
async def cmd_resetfarm(ctx: commands.Context, user_id: str = ""):
    if not user_id:
        await ctx.send(embed=err_e("Usage: `!resetfarm <user_id>`"))
        return
    await db.reset_farm_stats(user_id)
    await ctx.send(embed=ok_e("✅ Reset", f"Farm stats cleared for `{user_id}`."))


@bot.command(name="serverinfo")
@owner_only()
async def cmd_serverinfo(ctx: commands.Context, server_id: str = ""):
    if not server_id:
        await ctx.send(embed=err_e("Usage: `!serverinfo <server_id>`"))
        return
    wl = await db.has_server_access(server_id)
    g = bot.get_guild(int(server_id))
    e = info_e(f"🏠 Server `{server_id}`")
    e.add_field(name="Whitelisted", value="✅" if wl else "❌", inline=True)
    e.add_field(name="Bot in Server", value="✅" if g else "❌", inline=True)
    if g:
        e.add_field(name="Name", value=g.name, inline=True)
        e.add_field(name="Members", value=str(g.member_count), inline=True)
    await ctx.send(embed=e)


@bot.command(name="announce")
@owner_only()
async def cmd_announce(ctx: commands.Context, *, message: str = ""):
    if not message:
        await ctx.send(embed=err_e("Usage: `!announce <message>`"))
        return
    users = await db.get_all_authorized(limit=500)
    status = await ctx.send(embed=info_e("📢 Announcing…", f"Sending to {len(users)} users…"))
    sent = failed = 0
    for u in users:
        try:
            member = await bot.fetch_user(int(u["user_id"]))
            e = discord.Embed(title="📢 Announcement", description=message, color=0xF1C40F)
            e.set_footer(text="FarmBot")
            await member.send(embed=e)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)
    await status.edit(embed=ok_e("📢 Done", f"✅ Sent: `{sent}`  ❌ Failed (DMs closed): `{failed}`"))


@bot.command(name="botinfo")
@owner_only()
async def cmd_botinfo(ctx: commands.Context):
    total = await db.count_authorized()
    gs = await db.global_farm_stats()
    sc = len(await db.list_server_access())
    uc = len(await db.list_user_access())
    e = info_e("🤖 FarmBot Info",
               f"**Guilds:** `{len(bot.guilds)}`\n"
               f"**Authorized users:** `{total}`\n"
               f"**Farm access users:** `{uc}`\n"
               f"**Whitelisted servers:** `{sc}`\n"
               f"**Total farm runs:** `{gs['runs']}`\n"
               f"**Total members added:** `{gs['total']}`\n"
               f"**Latency:** `{round(bot.latency*1000)}ms`")
    await ctx.send(embed=e)


@bot.command(name="settutorial")
@owner_only()
async def cmd_settutorial(ctx: commands.Context, *, text: str = ""):
    if not text:
        await ctx.send(embed=err_e("Usage: `!settutorial <text>`\nTip: use `\\n` for newlines."))
        return
    text = text.replace("\\n", "\n")
    await db.set_config("tutorial", text)
    preview = text[:300] + ("…" if len(text) > 300 else "")
    await ctx.send(embed=ok_e("✅ Tutorial Updated", f"Preview:\n\n{preview}"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SLASH COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.tree.command(name="ping", description="Check FarmBot latency")
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=ok_e("🏓 Pong!", f"Latency: **{round(bot.latency*1000)}ms**"))


@bot.tree.command(name="help", description="Show all FarmBot commands")
async def slash_help(interaction: discord.Interaction):
    e = await build_embed("help")
    e.add_field(name="🔑 Auth", value="`/lauth`  `/addbot`  `/authbot`  `/myauth`  `/authcount`", inline=False)
    e.add_field(name="🌾 Farm", value="`/farm`  `/farmstats`  `/roles`  `/tutorial`", inline=False)
    e.add_field(name="⚙️ Roles", value="`/giverole`  `/removerole`", inline=False)
    e.add_field(name="👑 Owner", value="`/ownerhelp`", inline=False)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="lauth", description="Show the authorization embed with add-bot and auth-bot buttons")
async def slash_lauth(interaction: discord.Interaction):
    e = await build_embed("lauth")
    e.add_field(
        name="📊 Role Tiers",
        value="\n".join(f"• `{t.capitalize()}` — {l} members / farm" for t, l in ROLE_TIERS.items()),
        inline=False,
    )
    await interaction.response.send_message(embed=e, view=AuthView())


@bot.tree.command(name="addbot", description="Get the link to add FarmBot to your server")
async def slash_addbot(interaction: discord.Interaction):
    invite = make_invite_url()
    e = await build_embed("addbot", invite_url=invite)
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="authbot", description="Authorize yourself to be added to servers via FarmBot")
async def slash_authbot(interaction: discord.Interaction):
    oauth = make_oauth_url(interaction.user.id)
    if not oauth:
        await interaction.response.send_message(embed=err_e("❌ Redirect URI not configured."), ephemeral=True)
        return
    e = await build_embed("authbot", oauth_url=oauth)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="tutorial", description="Show how to get members with FarmBot")
async def slash_tutorial(interaction: discord.Interaction):
    text = await db.get_config("tutorial")
    e = await build_embed("tutorial")
    e.description = text or e.description
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="myauth", description="Check your own authorization status")
async def slash_myauth(interaction: discord.Interaction):
    user = await db.get_authorized_user(str(interaction.user.id))
    has_access = await db.has_user_access(str(interaction.user.id))
    if user:
        ts  = datetime.fromtimestamp(user["authorized_at"]).strftime("%Y-%m-%d %H:%M")
        exp = datetime.fromtimestamp(user["token_expires"]).strftime("%Y-%m-%d %H:%M")
        e = ok_e("✅ You are authorized!", f"Authorized: `{ts}`\nExpires: `{exp}`")
        e.add_field(name="Farm Access", value="✅" if (has_access or is_owner(interaction.user.id)) else "❌", inline=True)
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        if member:
            tier = get_user_tier(member)
            e.add_field(name="Tier", value=f"`{tier.capitalize()}`", inline=True)
            e.add_field(name="Limit", value=f"{ROLE_TIERS.get(tier,2)}/cmd", inline=True)
    else:
        e = err_e("❌ Not authorized. Use `/authbot` to authorize.")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="authcount", description="Show total authorized users and farm stats")
async def slash_authcount(interaction: discord.Interaction):
    total = await db.count_authorized()
    gs = await db.global_farm_stats()
    e = info_e("📊 Stats", f"**Authorized Users:** `{total}`\n**Farm Runs:** `{gs['runs']}`\n**Members Added:** `{gs['total']}`")
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="roles", description="View role tiers and their farm limits")
async def slash_roles(interaction: discord.Interaction):
    e = info_e("🏷️ Role Tiers", "\n".join(f"• `{t.capitalize()}` — **{l}** members / farm" for t, l in ROLE_TIERS.items()))
    e.set_footer(text="Ask an admin to assign your role")
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="farmstats", description="View your personal farm history")
async def slash_farmstats(interaction: discord.Interaction):
    stats = await db.get_farm_stats(str(interaction.user.id))
    member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
    tier = get_user_tier(member) if member else "unknown"
    e = info_e(f"🌾 Farm Stats", f"**Runs:** `{stats['times']}`\n**Added:** `{stats['total']}`\n**Tier:** `{tier.capitalize()}`")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="farm", description="Add authorized members to a server")
@app_commands.describe(server_id="The Discord server ID to farm members into")
async def slash_farm(interaction: discord.Interaction, server_id: str):
    await _do_farm(interaction, server_id)


@bot.tree.command(name="giverole", description="Give a role to a member")
@app_commands.describe(member="The member to give the role to", role_name="The exact role name")
@app_commands.checks.has_permissions(manage_roles=True)
async def slash_giverole(interaction: discord.Interaction, member: discord.Member, role_name: str):
    role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), interaction.guild.roles)
    if not role:
        await interaction.response.send_message(embed=err_e(f"Role `{role_name}` not found."), ephemeral=True)
        return
    if role >= interaction.guild.me.top_role:
        await interaction.response.send_message(embed=err_e("❌ That role is above my highest role."), ephemeral=True)
        return
    await member.add_roles(role)
    await interaction.response.send_message(embed=ok_e("✅ Done", f"Gave **{role.name}** to {member.mention}."))


@bot.tree.command(name="removerole", description="Remove a role from a member")
@app_commands.describe(member="The member to remove the role from", role_name="The exact role name")
@app_commands.checks.has_permissions(manage_roles=True)
async def slash_removerole(interaction: discord.Interaction, member: discord.Member, role_name: str):
    role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), interaction.guild.roles)
    if not role:
        await interaction.response.send_message(embed=err_e(f"Role `{role_name}` not found."), ephemeral=True)
        return
    if role not in member.roles:
        await interaction.response.send_message(embed=err_e(f"{member.mention} doesn't have that role."), ephemeral=True)
        return
    await member.remove_roles(role)
    await interaction.response.send_message(embed=ok_e("✅ Done", f"Removed **{role.name}** from {member.mention}."))


# ── OWNER SLASH COMMANDS ──────────────────────────────────────────────────

@bot.tree.command(name="ownerhelp", description="Show all owner commands")
async def slash_ownerhelp(interaction: discord.Interaction):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    e = discord.Embed(title="👑 Owner Slash Commands", color=0xF1C40F)
    e.add_field(name="Access", value="`/giveaccess` `/removeaccess` `/listusers` `/clearauth`", inline=False)
    e.add_field(name="Servers", value="`/grantserver` `/revokeserver` `/listservers` `/serverinfo`", inline=False)
    e.add_field(name="Management", value="`/resetfarm` `/announce` `/botinfo`", inline=False)
    e.add_field(name="Config", value="`/editembed` `/settutorial`", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="editembed", description="[Owner] Edit any bot embed using a dropdown")
async def slash_editembed(interaction: discord.Interaction):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    e = info_e("✏️ Edit Embed", "Select which embed to edit from the dropdown below.")
    await interaction.response.send_message(embed=e, view=EmbedSelectView(), ephemeral=True)


@bot.tree.command(name="editmsg", description="[Owner] Edit a message the bot sent (text + embed)")
@app_commands.describe(
    message_id="ID of the message to edit (right-click message → Copy ID)",
    channel_id="Channel ID if the message isn't in this channel (optional)",
)
async def slash_editmsg(interaction: discord.Interaction, message_id: str, channel_id: str = ""):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    try:
        ch = interaction.channel if not channel_id else bot.get_channel(int(channel_id))
        if ch is None:
            await interaction.response.send_message(embed=err_e(f"❌ Channel `{channel_id}` not found."), ephemeral=True)
            return
        msg = await ch.fetch_message(int(message_id))
    except discord.NotFound:
        await interaction.response.send_message(embed=err_e(f"❌ Message `{message_id}` not found in that channel."), ephemeral=True)
        return
    except ValueError:
        await interaction.response.send_message(embed=err_e("❌ Invalid message or channel ID."), ephemeral=True)
        return
    if msg.author.id != bot.user.id:
        await interaction.response.send_message(embed=err_e("❌ That message wasn't sent by me — I can only edit my own messages."), ephemeral=True)
        return
    await interaction.response.send_modal(MsgEditModal(msg))


@bot.tree.command(name="giveaccess", description="[Owner] Grant a user farm access")
@app_commands.describe(user_id="Discord user ID")
async def slash_giveaccess(interaction: discord.Interaction, user_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    await db.grant_user_access(user_id, str(interaction.user.id))
    await interaction.response.send_message(embed=ok_e("✅ Done", f"`{user_id}` can now use farm."), ephemeral=True)


@bot.tree.command(name="removeaccess", description="[Owner] Revoke a user's farm access")
@app_commands.describe(user_id="Discord user ID")
async def slash_removeaccess(interaction: discord.Interaction, user_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    ok = await db.revoke_user_access(user_id)
    await interaction.response.send_message(
        embed=(ok_e("✅ Done", f"Access revoked for `{user_id}`.") if ok else err_e(f"`{user_id}` had no access.")),
        ephemeral=True)


@bot.tree.command(name="grantserver", description="[Owner] Whitelist a server for farming")
@app_commands.describe(server_id="Discord server ID")
async def slash_grantserver(interaction: discord.Interaction, server_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    await db.grant_server_access(server_id, str(interaction.user.id))
    g = bot.get_guild(int(server_id))
    await interaction.response.send_message(
        embed=ok_e("✅ Server Whitelisted", f"`{server_id}` ({g.name if g else 'Unknown'}) approved."), ephemeral=True)


@bot.tree.command(name="revokeserver", description="[Owner] Remove a server from the whitelist")
@app_commands.describe(server_id="Discord server ID")
async def slash_revokeserver(interaction: discord.Interaction, server_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    ok = await db.revoke_server_access(server_id)
    await interaction.response.send_message(
        embed=(ok_e("✅ Done", f"`{server_id}` removed.") if ok else err_e("Not found.")), ephemeral=True)


@bot.tree.command(name="listservers", description="[Owner] List all whitelisted servers")
async def slash_listservers(interaction: discord.Interaction):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    rows = await db.list_server_access()
    if not rows:
        await interaction.response.send_message(embed=info_e("📋 Servers", "None yet."), ephemeral=True)
        return
    lines = []
    for r in rows[:20]:
        g = bot.get_guild(int(r["server_id"]))
        ts = datetime.fromtimestamp(r["granted_at"]).strftime("%Y-%m-%d")
        lines.append(f"`{r['server_id']}` — **{g.name if g else 'Unknown'}** ({ts})")
    e = info_e("📋 Whitelisted Servers", "\n".join(lines))
    e.set_footer(text=f"{len(rows)} total")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="listusers", description="[Owner] List users with farm access")
async def slash_listusers(interaction: discord.Interaction):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    rows = await db.list_user_access()
    if not rows:
        await interaction.response.send_message(embed=info_e("📋 Users", "None yet."), ephemeral=True)
        return
    lines = [f"`{r['user_id']}` — {datetime.fromtimestamp(r['granted_at']).strftime('%Y-%m-%d')}" for r in rows[:20]]
    e = info_e("📋 Farm Access Users", "\n".join(lines))
    e.set_footer(text=f"{len(rows)} total")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="clearauth", description="[Owner] Remove a user's OAuth token")
@app_commands.describe(user_id="Discord user ID")
async def slash_clearauth(interaction: discord.Interaction, user_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    ok = await db.delete_authorized_user(user_id)
    await interaction.response.send_message(
        embed=(ok_e("✅ Cleared", f"Removed token for `{user_id}`.") if ok else err_e("Not found.")), ephemeral=True)


@bot.tree.command(name="resetfarm", description="[Owner] Reset a user's farm stats")
@app_commands.describe(user_id="Discord user ID")
async def slash_resetfarm(interaction: discord.Interaction, user_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    await db.reset_farm_stats(user_id)
    await interaction.response.send_message(embed=ok_e("✅ Reset", f"Farm stats cleared for `{user_id}`."), ephemeral=True)


@bot.tree.command(name="serverinfo", description="[Owner] Get info about a server")
@app_commands.describe(server_id="Discord server ID")
async def slash_serverinfo(interaction: discord.Interaction, server_id: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    wl = await db.has_server_access(server_id)
    g  = bot.get_guild(int(server_id))
    e  = info_e(f"🏠 Server `{server_id}`")
    e.add_field(name="Whitelisted", value="✅" if wl else "❌", inline=True)
    e.add_field(name="Bot in Server", value="✅" if g else "❌", inline=True)
    if g:
        e.add_field(name="Name", value=g.name, inline=True)
        e.add_field(name="Members", value=str(g.member_count), inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="announce", description="[Owner] DM all authorized users an announcement")
@app_commands.describe(message="The announcement message")
async def slash_announce(interaction: discord.Interaction, message: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    users = await db.get_all_authorized(limit=500)
    sent = failed = 0
    for u in users:
        try:
            member = await bot.fetch_user(int(u["user_id"]))
            e = discord.Embed(title="📢 Announcement", description=message, color=0xF1C40F)
            e.set_footer(text="FarmBot")
            await member.send(embed=e)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)
    await interaction.followup.send(embed=ok_e("📢 Done", f"✅ Sent: `{sent}`  ❌ Failed: `{failed}`"))


@bot.tree.command(name="botinfo", description="[Owner] Show bot statistics")
async def slash_botinfo(interaction: discord.Interaction):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    total = await db.count_authorized()
    gs = await db.global_farm_stats()
    sc = len(await db.list_server_access())
    uc = len(await db.list_user_access())
    e = info_e("🤖 FarmBot Info",
               f"**Guilds:** `{len(bot.guilds)}`\n**Authorized:** `{total}`\n"
               f"**Farm access users:** `{uc}`\n**Whitelisted servers:** `{sc}`\n"
               f"**Farm runs:** `{gs['runs']}`\n**Members added:** `{gs['total']}`\n"
               f"**Latency:** `{round(bot.latency*1000)}ms`")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="settutorial", description="[Owner] Edit the tutorial text")
@app_commands.describe(text="New tutorial text (use \\n for newlines)")
async def slash_settutorial(interaction: discord.Interaction, text: str):
    if not is_owner(interaction.user.id):
        await interaction.response.send_message(embed=err_e("❌ Owner only."), ephemeral=True)
        return
    text = text.replace("\\n", "\n")
    await db.set_config("tutorial", text)
    preview = text[:300] + ("…" if len(text) > 300 else "")
    await interaction.response.send_message(
        embed=ok_e("✅ Tutorial Updated", f"Preview:\n\n{preview}"), ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────
#  Error handler
# ──────────────────────────────────────────────────────────────────────────

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=err_e("❌ You need **Manage Roles** permission."))
    elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
        await ctx.send(embed=err_e("❌ Member not found."))
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.CheckFailure):
        pass
    else:
        await ctx.send(embed=err_e(f"❌ {error}"))


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = str(error)
    if interaction.response.is_done():
        await interaction.followup.send(embed=err_e(f"❌ {msg}"), ephemeral=True)
    else:
        await interaction.response.send_message(embed=err_e(f"❌ {msg}"), ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌  DISCORD_BOT_TOKEN is not set!")
        sys.exit(1)
    bot.run(BOT_TOKEN)
