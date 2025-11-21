import os
import sys
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv

import discord
from discord.ext import commands

# ---------------------------
# Load token from .env
# ---------------------------
load_dotenv()
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("TOKEN not found in .env. Exiting.")
    sys.exit(1)

# ---------------------------
# Configuration (set by you)
# ---------------------------
# The server where staff will receive modmail tickets
STAFF_GUILD_ID = 1438617538874441781
# The category inside the staff server where modmail channels are created
MODMAIL_CATEGORY_ID = 1438618584627810405
# Bot owner (has access to owner-only commands)
OWNER_ID = 822530323505741834
# Role ID that represents staff who can reply to tickets
STAFF_ROLE_ID = 1434738274269794376

# Command prefix and intents
COMMAND_PREFIX = "?"
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.dm_messages = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
bot.remove_command("help")

# ---------------------------
# Helpers
# ---------------------------
def sanitize_channel_name(name: str, user_id: int) -> str:
    # Create a safe channel name like: modmail-username-1234
    cleaned = re.sub(r"[^a-z0-9\-]", "-", name.lower())
    # Limit length to avoid Discord name limits
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return f"modmail-{cleaned[:60]}-{user_id}"

def is_owner_check(ctx):
    return ctx.author.id == OWNER_ID

def has_staff_role(member: discord.Member) -> bool:
    if member is None:
        return False
    # Owner always counts as staff
    if member.id == OWNER_ID:
        return True
    return any(r.id == STAFF_ROLE_ID for r in getattr(member, "roles", []))

# Small utility to fetch staff guild and category, with helpful errors
async def get_staff_guild_and_category():
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        # attempt to fetch (rare case)
        try:
            guild = await bot.fetch_guild(STAFF_GUILD_ID)  # may raise
        except Exception:
            return None, None
    category = guild.get_channel(MODMAIL_CATEGORY_ID) if guild else None
    return guild, category

# ---------------------------
# Events
# ---------------------------
@bot.event
async def on_ready():
    print(f"[{datetime.utcnow().isoformat()}] Logged in as {bot.user} (ID: {bot.user.id})")
    # attempt tree sync quietly
    try:
        await bot.tree.sync()
    except Exception:
        pass

@bot.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Handle direct messages from users -> forward to staff server
    if isinstance(message.channel, discord.DMChannel):
        guild, category = await get_staff_guild_and_category()
        if guild is None or category is None:
            # Inform the user that modmail isn't configured
            try:
                await message.channel.send("RTN Union staff inbox isn't currently configured. Please try again later.")
            except Exception:
                pass
            return

        # Look for an existing ticket channel by topic (topic stores user id)
        existing_channel = None
        for ch in category.text_channels:
            try:
                if ch.topic and ch.topic.strip() == str(message.author.id):
                    existing_channel = ch
                    break
            except Exception:
                continue

        if existing_channel is None:
            # Create channel with permissions: only staff role & bot can view
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            # Give staff role access
            staff_role = guild.get_role(STAFF_ROLE_ID)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

            channel_name = sanitize_channel_name(message.author.name, message.author.id)
            try:
                new_channel = await guild.create_text_channel(
                    name=channel_name,
                    overwrites=overwrites,
                    category=category,
                    topic=str(message.author.id),
                    reason=f"ModMail opened by {message.author} ({message.author.id})"
                )
            except discord.Forbidden:
                # can't create channel
                try:
                    await message.channel.send("RTN Union bot lacks permission to create modmail channels. Contact staff.")
                except Exception:
                    pass
                return
            except Exception:
                # fallback: try a simpler name
                fallback_name = f"modmail-{message.author.id}"
                new_channel = await guild.create_text_channel(
                    name=fallback_name,
                    overwrites=overwrites,
                    category=category,
                    topic=str(message.author.id),
                    reason=f"ModMail opened by {message.author} ({message.author.id})"
                )

            existing_channel = new_channel
            # Post an opening message
            try:
                await existing_channel.send(
                    embed=discord.Embed(
                        title="📬 New ModMail",
                        description=f"**From:** {message.author} (`{message.author.id}`)\n\nUse `?reply <message>` to reply and `?close` to close the ticket.",
                        color=discord.Color.blurple()
                    )
                )
            except Exception:
                pass

        # Relay DM content to the staff channel
        relay_parts = []
        if message.content:
            relay_parts.append(message.content)
        # Attachments as URLs
        for att in message.attachments:
            relay_parts.append(att.url)
        relay_text = "\n".join(relay_parts) or "(no content)"

        try:
            await existing_channel.send(f"**User ({message.author} — {message.author.id}):**\n{relay_text}")
        except Exception:
            pass

        # Confirm to the user
        try:
            await message.channel.send("✅ Your message has been forwarded to RTN Union Staff. They will respond here.")
        except Exception:
            pass

        return

    # Otherwise, normal message -> allow commands to process
    await bot.process_commands(message)

# ---------------------------
# Commands: Staff interaction
# ---------------------------
@bot.command(name="reply")
async def cmd_reply(ctx: commands.Context, *, message_text: str):
    """
    Reply to the user who opened the modmail.
    Usage: ?reply <message>
    Only usable by staff role or owner inside a modmail channel.
    """
    # Only allow in guild text channels
    if ctx.guild is None:
        await ctx.reply("This command must be used in a server channel (the staff inbox).")
        return

    # Only allow in modmail channels (we set topic to user ID)
    if not ctx.channel.topic or not ctx.channel.topic.strip().isdigit():
        await ctx.reply("This does not appear to be a modmail ticket (no user ID found).")
        return

    # Permission check: must be staff role or owner
    if not has_staff_role(ctx.author):
        await ctx.reply("You do not have permission to reply to modmail.")
        return

    user_id = int(ctx.channel.topic.strip())
    try:
        user = await bot.fetch_user(user_id)
    except Exception:
        await ctx.reply("Could not fetch the user (they may not exist).")
        return

    # Send message to user
    try:
        sent = await user.send(f"**RTN Union Staff:**\n{message_text}")
        await ctx.send(f"📤 Sent reply to {user.mention}.")
    except discord.Forbidden:
        await ctx.send("❌ Could not send message to the user (they may have DMs disabled).")
    except Exception as e:
        await ctx.send(f"⚠️ Error sending message: {e}")

@bot.command(name="close")
async def cmd_close(ctx: commands.Context):
    """
    Close the modmail ticket (deletes the channel).
    Usable by staff or owner inside a modmail channel.
    """
    if ctx.guild is None:
        await ctx.reply("This must be used inside a server channel.")
        return

    if not ctx.channel.topic or not ctx.channel.topic.strip().isdigit():
        await ctx.reply("This doesn't look like a modmail ticket.")
        return

    # Permission check
    if not has_staff_role(ctx.author):
        await ctx.reply("You do not have permission to close tickets.")
        return

    user_id = int(ctx.channel.topic.strip())
    # Notify the user if possible
    try:
        user = await bot.fetch_user(user_id)
        try:
            await user.send("📪 Your ModMail ticket with RTN Union has been closed. If you need further help, DM again.")
        except Exception:
            pass
    except Exception:
        pass

    try:
        await ctx.send("🔒 Ticket closed — deleting channel...")
        await ctx.channel.delete()
    except Exception as e:
        await ctx.send(f"Could not delete channel: {e}")

# ---------------------------
# Owner-only utilities
# ---------------------------
def owner_only():
    return commands.check(lambda ctx: ctx.author.id == OWNER_ID)

@bot.command(name="shutdown")
@owner_only()
async def cmd_shutdown(ctx: commands.Context):
    await ctx.send("🛑 Owner request: Shutting down.")
    await bot.close()

@bot.command(name="restart")
@owner_only()
async def cmd_restart(ctx: commands.Context):
    await ctx.send("🔄 Owner request: Restarting.")
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@bot.command(name="forceclose")
@owner_only()
async def cmd_forceclose(ctx: commands.Context, channel_name: str = None):
    """
    Force-close a modmail channel by name (or current channel if not specified).
    Usage: ?forceclose [channel-name]
    """
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        await ctx.send("Staff guild not available.")
        return

    target = None
    if channel_name:
        target = discord.utils.get(guild.channels, name=channel_name)
    else:
        # If invoked from within the staff guild and a modmail channel
        if ctx.guild and ctx.guild.id == STAFF_GUILD_ID:
            target = ctx.channel
    if target is None:
        await ctx.send("Channel not found.")
        return

    try:
        await target.delete()
        await ctx.send("Channel deleted.")
    except Exception as e:
        await ctx.send(f"Failed to delete channel: {e}")

@bot.command(name="broadcast")
@owner_only()
async def cmd_broadcast(ctx: commands.Context, *, message_text: str):
    """
    Owner-only: broadcast a DM to all members of the staff guild who have DMs open.
    Use sparingly.
    """
    guild = bot.get_guild(STAFF_GUILD_ID)
    if guild is None:
        await ctx.send("Staff guild not available.")
        return

    sent = 0
    failed = 0
    await ctx.send("Broadcast starting...")
    for member in guild.members:
        # skip bots
        if member.bot:
            continue
        try:
            await member.send(f"**Owner Broadcast:**\n{message_text}")
            sent += 1
            await asyncio.sleep(0.25)  # small delay to be courteous
        except Exception:
            failed += 1
    await ctx.send(f"Broadcast finished. Sent: {sent}. Failed: {failed}.")

@bot.command(name="eval")
@owner_only()
async def cmd_eval(ctx: commands.Context, *, code: str):
    """
    Owner-only eval. Runs Python code. Use at your own risk.
    This is intentionally powerful and restricted to OWNER only.
    """
    env = {
        "bot": bot,
        "discord": discord,
        "commands": commands,
        "ctx": ctx,
        "asyncio": asyncio,
        "__name__": "__main__",
    }
    # Wrap in coroutine to allow await usage
    to_eval = f"async def __owner_eval_fn():\n"
    for line in code.splitlines():
        to_eval += "    " + line + "\n"

    try:
        exec(to_eval, env)
        func = env["__owner_eval_fn"]
        result = await func()
        await ctx.send(f"✅ Eval result: ```{result}```")
    except Exception as e:
        await ctx.send(f"❌ Eval error: ```{e}```")

# ---------------------------
# Simple admin/status utilities
# ---------------------------
@bot.command(name="whoami")
async def cmd_whoami(ctx: commands.Context):
    await ctx.send(f"You are {ctx.author} (ID: {ctx.author.id}).")

@bot.command(name="inboxinfo")
async def cmd_inboxinfo(ctx: commands.Context):
    """
    Shows basic info about the configured staff guild and category.
    """
    guild = bot.get_guild(STAFF_GUILD_ID)
    if not guild:
        await ctx.send("Staff guild not accessible by the bot.")
        return
    category = guild.get_channel(MODMAIL_CATEGORY_ID)
    await ctx.send(f"Staff guild: {guild.name} (`{guild.id}`)\nCategory: {category.name if category else 'NOT FOUND'} (`{MODMAIL_CATEGORY_ID}`)")

# ---------------------------
# Run the bot
# ---------------------------
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("Interrupted, shutting down.")
    except Exception as e:
        print(f"Bot error: {e}")
