import os
import re
import sys
import asyncio
from datetime import datetime
from dotenv import load_dotenv

import discord
from discord.ext import commands
from discord import PermissionOverwrite

# ---------------------------
# Load token from .env
# ---------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("DISCORD_TOKEN not found in .env. Exiting.")
    sys.exit(1)

# ---------------------------
# Configuration (embedded)
# ---------------------------
STAFF_GUILD_ID = 1412183104960856227         # Staff server (guild) ID
MODMAIL_CATEGORY_ID = 1434738351356772354   # Category ID for modmail channels
OWNER_ID = 822530323505741834                # Bot owner ID
STAFF_ROLE_ID = 1434738274269794376          # Role ID for staff who can see/reply

COMMAND_PREFIX = "!"
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.dm_messages = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
bot.remove_command("help")

# ---------------------------
# Helpers
# ---------------------------
def sanitize_channel_name(name: str, user_id: int) -> str:
    # Lowercase, keep alphanumerics and hyphens, trim length to be safe
    base = re.sub(r"[^a-z0-9\-]", "-", name.lower().replace(" ", "-"))
    base = re.sub(r"-{2,}", "-", base).strip("-")
    if not base:
        base = "user"
    return f"modmail-{base}-{user_id}"

def is_owner_check(ctx: commands.Context) -> bool:
    return ctx.author.id == OWNER_ID

def has_staff_role(member: discord.Member) -> bool:
    if member is None:
        return False
    if member.id == OWNER_ID:
        return True
    return any(r.id == STAFF_ROLE_ID for r in getattr(member, "roles", []))

def format_ts() -> str:
    return datetime.utcnow().isoformat()

# ---------------------------
# Events
# ---------------------------
@bot.event
async def on_ready():
    print(f"[{format_ts()}] Logged in as {bot.user} (ID: {bot.user.id})")
    print("RTN Union ModMail (staff-only visibility) running.")
    # Attempt to sync application commands quietly (if any)
    try:
        await bot.tree.sync()
    except Exception:
        pass

@bot.event
async def on_message(message: discord.Message):
    # ignore bots
    if message.author.bot:
        return

    # If DM -> create/forward ticket in staff guild
    if isinstance(message.channel, discord.DMChannel):
        await _handle_dm_to_staff(message)
        return

    # otherwise process commands normally
    await bot.process_commands(message)

# ---------------------------
# Core: handle DM -> staff ticket
# ---------------------------
async def _handle_dm_to_staff(message: discord.DMChannel):
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        try:
            await message.author.send("RTN Union staff server not accessible. Please contact staff another way.")
        except Exception:
            pass
        print(f"[{format_ts()}] ERROR: Bot not in staff guild ({STAFF_GUILD_ID}).")
        return

    category = guild.get_channel(MODMAIL_CATEGORY_ID)
    if category is None:
        try:
            await message.author.send("ModMail category not found. Please contact staff another way.")
        except Exception:
            pass
        print(f"[{format_ts()}] ERROR: ModMail category {MODMAIL_CATEGORY_ID} not found in guild {guild.id}.")
        return

    # Build channel name and check for existing ticket
    channel_name = sanitize_channel_name(message.author.name, message.author.id)
    existing = None
    # category may be a CategoryChannel; use its .channels
    try:
        for ch in getattr(category, "channels", []):
            if ch.name == channel_name:
                existing = ch
                break
    except Exception:
        existing = None

    if existing:
        # forward the message to existing channel
        try:
            await existing.send(f"**User ({message.author} — {message.author.id}):**\n{message.content or '(no text)'}")
            for att in message.attachments:
                await existing.send(att.url)
        except Exception as e:
            print(f"[{format_ts()}] WARN: failed to forward to existing channel: {e}")
        try:
            await message.author.send("✅ Your message was added to the existing ticket. Staff will respond here.")
        except Exception:
            pass
        return

    # Resolve role & default role safely
    everyone_role = guild.default_role
    staff_role = guild.get_role(STAFF_ROLE_ID)
    bot_member = guild.me

    # If staff role doesn't exist, fall back to owner-only view (prevent crash)
    if staff_role is None:
        print(f"[{format_ts()}] WARNING: Staff role {STAFF_ROLE_ID} not found in guild {guild.id}. Creating channel visible only to staff via owner/admins fallback.")
        overwrites = {
            everyone_role: PermissionOverwrite(view_channel=False, send_messages=False),
            bot_member: PermissionOverwrite(view_channel=True, send_messages=True),
        }
    else:
        # Staff-only visibility: @everyone cannot see, staff can view+send
        overwrites = {
            everyone_role: PermissionOverwrite(view_channel=False, send_messages=False),
            staff_role: PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            bot_member: PermissionOverwrite(view_channel=True, send_messages=True),
        }

    # Create the channel under the category
    try:
        channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category,
            topic=str(message.author.id),
            reason=f"ModMail opened by {message.author} ({message.author.id})"
        )
    except discord.Forbidden as e:
        print(f"[{format_ts()}] ERROR: missing permission to create channel: {e}")
        try:
            await message.author.send("RTN Union bot lacks permission to create modmail channels. Contact staff.")
        except Exception:
            pass
        return
    except Exception as e:
        print(f"[{format_ts()}] ERROR: failed to create modmail channel: {e}")
        try:
            await message.author.send("An error occurred while opening your ticket. Please try again later.")
        except Exception:
            pass
        return

    # Announce in channel
    try:
        await channel.send(
            embed=discord.Embed(
                title="📬 New ModMail Ticket",
                description=f"**From:** {message.author} (`{message.author.id}`)\n\nUse `!reply <message>` to reply, `!close` to close the ticket.",
                color=discord.Color.blurple()
            )
        )
        # send the initial content & attachments
        if message.content:
            await channel.send(f"**User message:**\n{message.content}")
        for att in message.attachments:
            await channel.send(att.url)
    except Exception as e:
        print(f"[{format_ts()}] WARN: failed to send initial messages in ticket channel: {e}")

    # Confirm to user
    try:
        await message.author.send("✅ Your message has been forwarded to RTN Union staff. They will reply here via DM.")
    except Exception:
        pass

# ---------------------------
# Staff command: reply
# ---------------------------
@bot.command(name="reply")
async def cmd_reply(ctx: commands.Context, *, reply_text: str):
    # ensure we're inside staff guild and a modmail channel
    if ctx.guild is None or ctx.guild.id != STAFF_GUILD_ID:
        return await ctx.send("This command can only be used in the staff server inside a ticket channel.", delete_after=10)

    # must be a modmail channel (we store user id in topic)
    if not ctx.channel.topic or not ctx.channel.topic.strip().isdigit():
        return await ctx.send("This does not appear to be a modmail ticket (no user id in topic).", delete_after=10)

    # permission check: staff role or owner
    if not has_staff_role(ctx.author):
        return await ctx.send("You do not have permission to reply to tickets.", delete_after=10)

    user_id = int(ctx.channel.topic.strip())
    try:
        user = await bot.fetch_user(user_id)
    except Exception:
        return await ctx.send("Could not fetch the user (they may not exist).", delete_after=10)

    # send as DM to user
    try:
        await user.send(f"📣 **RTN Union Staff Reply:**\n{reply_text}")
        await ctx.send(f"✅ Reply sent to {user}.")
    except discord.Forbidden:
        await ctx.send("❌ Could not DM the user (their DMs may be closed).")
    except Exception as e:
        await ctx.send(f"⚠️ Error sending DM: {e}")

# ---------------------------
# Staff command: close ticket
# ---------------------------
@bot.command(name="close")
async def cmd_close(ctx: commands.Context):
    if ctx.guild is None or ctx.guild.id != STAFF_GUILD_ID:
        return await ctx.send("This command must be used in the staff server inside a ticket channel.", delete_after=10)

    if not ctx.channel.topic or not ctx.channel.topic.strip().isdigit():
        return await ctx.send("This does not appear to be a modmail ticket (no user id in topic).", delete_after=10)

    if not has_staff_role(ctx.author):
        return await ctx.send("You do not have permission to close tickets.", delete_after=10)

    user_id = int(ctx.channel.topic.strip())
    # notify user
    try:
        user = await bot.fetch_user(user_id)
        try:
            await user.send("📪 Your ModMail ticket with RTN Union has been closed. If you need further help, DM us again.")
        except Exception:
            pass
    except Exception:
        pass

    await ctx.send("🔒 Ticket will be deleted in 3 seconds...")
    await asyncio.sleep(3)
    try:
        await ctx.channel.delete()
    except Exception as e:
        await ctx.send(f"Could not delete the channel: {e}")

# ---------------------------
# Owner-only utilities
# ---------------------------
def owner_only():
    return commands.check(lambda ctx: ctx.author.id == OWNER_ID)

@bot.command(name="shutdown")
@owner_only()
async def cmd_shutdown(ctx: commands.Context):
    await ctx.send("🛑 Owner requested shutdown. Bye.")
    await bot.close()

@bot.command(name="restart")
@owner_only()
async def cmd_restart(ctx: commands.Context):
    await ctx.send("🔄 Owner requested restart. Restarting now...")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.command(name="forceclose")
@owner_only()
async def cmd_forceclose(ctx: commands.Context, channel_name: str = None):
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        return await ctx.send("Staff guild not available.")
    target = None
    if channel_name:
        target = discord.utils.get(guild.channels, name=channel_name)
    else:
        # if invoked in staff guild and current channel is a ticket, target that
        if ctx.guild and ctx.guild.id == STAFF_GUILD_ID:
            target = ctx.channel
    if target is None:
        return await ctx.send("Channel not found.")
    try:
        await target.delete()
        await ctx.send("Channel deleted.")
    except Exception as e:
        await ctx.send(f"Failed to delete channel: {e}")

@bot.command(name="broadcast")
@owner_only()
async def cmd_broadcast(ctx: commands.Context, *, message_text: str):
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        return await ctx.send("Staff guild not available.")
    sent = 0
    failed = 0
    await ctx.send("Broadcast starting...")
    for member in guild.members:
        if member.bot:
            continue
        try:
            await member.send(f"**Owner Broadcast:**\n{message_text}")
            sent += 1
            await asyncio.sleep(0.25)
        except Exception:
            failed += 1
    await ctx.send(f"Broadcast finished. Sent: {sent}. Failed: {failed}.")

@bot.command(name="eval")
@owner_only()
async def cmd_eval(ctx: commands.Context, *, code: str):
    env = {
        "bot": bot,
        "discord": discord,
        "commands": commands,
        "ctx": ctx,
        "asyncio": asyncio,
    }
    to_eval = "async def __owner_eval_fn():\n"
    for line in code.splitlines():
        to_eval += "    " + line + "\n"
    try:
        exec(to_eval, env)
        result = await env["__owner_eval_fn"]()
        await ctx.send(f"✅ Eval result: ```{result}```")
    except Exception as e:
        await ctx.send(f"❌ Eval error: ```{e}```")

# ---------------------------
# Utility commands
# ---------------------------
@bot.command(name="inboxinfo")
async def cmd_inboxinfo(ctx: commands.Context):
    guild = bot.get_guild(STAFF_GUILD_ID)
    if not guild:
        return await ctx.send("Staff guild not accessible by the bot.")
    category = guild.get_channel(MODMAIL_CATEGORY_ID)
    staff_role = guild.get_role(STAFF_ROLE_ID)
    await ctx.send(
        f"Staff guild: {guild.name} (`{guild.id}`)\n"
        f"Category: {category.name if category else 'NOT FOUND'} (`{MODMAIL_CATEGORY_ID}`)\n"
        f"Staff role: {staff_role.name if staff_role else 'NOT FOUND'} (`{STAFF_ROLE_ID}`)"
    )

@bot.command(name="whoami")
async def cmd_whoami(ctx: commands.Context):
    await ctx.send(f"You are {ctx.author} (ID: {ctx.author.id}).")

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("Interrupted, shutting down.")
    except Exception as e:
        print(f"Bot error: {e}")
