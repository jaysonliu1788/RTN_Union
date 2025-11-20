import os
import sys
import time
import random
import re
import asyncio
from datetime import datetime, timedelta

import pytz
import discord
from discord.ext import commands
from discord import app_commands

# ---------------------------
# Configuration
# ---------------------------
BOT_OWNER_ID = 1203091367429931040  # change to your Discord user ID
TOKEN = os.getenv("TOKEN")
GUILD_ID = 1364029087693144075  # replace with your server ID
CATEGORY_ID = 1365343722610491412  # replace with the ModMail category ID
ALLOWED_ROLE_ID = 1312911932927250442  # role allowed to use moderator commands (e.g. Moderator)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.dm_messages = True

client = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------
# Helpers / Checks
# ---------------------------
def is_owner():
    async def predicate(ctx):
        return ctx.author.id == BOT_OWNER_ID
    return commands.check(predicate)

def has_allowed_role():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        return any(r.id == ALLOWED_ROLE_ID for r in getattr(ctx.author, "roles", []))
    return commands.check(predicate)

# ---------------------------
# Startup
# ---------------------------
@client.event
async def on_ready():
    print(f"Logged in as: {client.user} ({client.user.id})")
    try:
        await client.tree.sync()
    except Exception:
        pass

# ---------------------------
# Owner / Maintenance Commands
# ---------------------------
@client.command(name="restart")
@is_owner()
async def restart(ctx):
    """Restart the bot (owner only)."""
    await ctx.send("Restarting the bot... Please wait.")
    # give Discord a moment to send the message
    await asyncio.sleep(1)
    os.execv(sys.executable, [sys.executable] + sys.argv)

@client.command(name="shutdown")
@is_owner()
async def shutdown(ctx):
    """Shutdown the bot (owner only)."""
    await ctx.send("Shutting down... Goodbye.")
    await client.close()

# ---------------------------
# Info / Utility Commands
# ---------------------------
@client.command()
async def info(ctx):
    embed = discord.Embed(
        title="🤖 Bot Information",
        description="Here's some info about me!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Bot Name", value=str(client.user), inline=True)
    embed.add_field(name="Bot ID", value=client.user.id, inline=True)
    embed.add_field(name="Guilds Connected", value=len(client.guilds), inline=True)
    embed.add_field(name="Latency", value=f"{round(client.latency * 1000)}ms", inline=True)
    embed.set_footer(text="Created by Dr.J")
    await ctx.send(embed=embed)

@client.command()
async def serverinfo(ctx):
    guild = ctx.guild
    if guild is None:
        await ctx.send("This command can only be used in a server.")
        return
    owner = guild.owner
    server_info = (
        f"**Server Info**\n"
        f"Server Name: {guild.name}\n"
        f"Owner: {owner}\n"
        f"Total Roles: {len(guild.roles)}\n"
        f"Total Channels: {len(guild.channels)}\n"
        f"Total Voice Channels: {len(guild.voice_channels)}\n"
        f"Total Members: {guild.member_count}\n"
    )
    await ctx.send(server_info)

@client.command()
async def ping(ctx):
    await ctx.send(f"Pong! {round(client.latency * 1000)}ms")

@client.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int):
    if amount <= 0:
        await ctx.send("Amount must be greater than 0.")
        return
    deleted = await ctx.channel.purge(limit=amount + 1)  # include command message
    msg = await ctx.send(f"Deleted {max(0, len(deleted)-1)} messages.")
    await asyncio.sleep(4)
    await msg.delete()

@client.command()
async def invite(ctx):
    await ctx.send("Click here to invite me to your server:\n<https://discord.com/oauth2/authorize?client_id=1346881154225279050&scope=bot%20applications.commands&permissions=8>")

@client.command()
async def support(ctx):
    await ctx.send("Join our support server here: https://discord.gg/ryHSPbat22")

@client.command()
async def cmds(ctx):
    commands_list = """
**List of Commands (prefix = !):**
!info, !serverinfo, !ping, !clear <amount>, !invite, !support, !cmds
!role <@user> <@role>, !unrole <@user> <@role> (mod role required)
!mute <@user> <duration>, !unmute <@user> (mod role required)
!warn <@user> <reason>, !warnings <@user>, !clearwarnings <@user>, !serverwarnings
!reply <message> (in modmail channel) , !close (in modmail channel)
Owner-only: !restart, !shutdown
Slash: /kick, /ban, /mute, /startgiveaway
"""
    await ctx.send(commands_list)

# ---------------------------
# Role Management
# ---------------------------
@client.command()
@has_allowed_role()
async def role(ctx, user: discord.Member, role: discord.Role):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send("You don't have permission to manage roles.")
        return
    try:
        if role.position >= ctx.author.top_role.position and not ctx.author.guild_permissions.administrator:
            await ctx.send("You cannot assign a role higher or equal to your highest role.")
            return
        if role.position >= ctx.guild.me.top_role.position:
            await ctx.send("I cannot assign that role because it is higher or equal to my highest role.")
            return
        await user.add_roles(role)
        await ctx.send(f"Assigned **{role.name}** to {user.mention}.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to assign roles.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@client.command()
@has_allowed_role()
async def unrole(ctx, user: discord.Member, role: discord.Role):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send("You don't have permission to manage roles.")
        return
    try:
        await user.remove_roles(role)
        await ctx.send(f"Removed **{role.name}** from {user.mention}.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to remove roles.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

# ---------------------------
# Mute / Unmute (role-based)
# ---------------------------
async def get_or_create_muted_role(guild: discord.Guild):
    mute_role = discord.utils.get(guild.roles, name="Muted")
    if mute_role:
        return mute_role
    try:
        mute_role = await guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False, speak=False))
        # update channel overwrites to prevent sending messages (best-effort)
        for ch in guild.text_channels:
            try:
                await ch.set_permissions(mute_role, send_messages=False)
            except Exception:
                pass
    except Exception:
        mute_role = None
    return mute_role

@client.command()
@has_allowed_role()
async def mute(ctx, user: discord.Member, duration: str):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send("You don't have permission to mute members.")
        return
    # Parse duration
    try:
        if duration.endswith('m'):
            seconds = int(duration[:-1]) * 60
        elif duration.endswith('h'):
            seconds = int(duration[:-1]) * 3600
        elif duration.endswith('d'):
            seconds = int(duration[:-1]) * 86400
        else:
            await ctx.send("Invalid duration format. Use 'm', 'h', or 'd'. Example: 10m, 2h, 1d.")
            return
    except ValueError:
        await ctx.send("Invalid duration number.")
        return

    mute_role = await get_or_create_muted_role(ctx.guild)
    if mute_role is None:
        await ctx.send("Could not create or find a Muted role.")
        return

    try:
        await user.add_roles(mute_role, reason=f"Muted by {ctx.author} for {duration}")
        await ctx.send(f"{user.mention} has been muted for {duration}.")
        await asyncio.sleep(seconds)
        if mute_role in user.roles:
            await user.remove_roles(mute_role)
            await ctx.send(f"{user.mention} has been unmuted (time elapsed).")
    except discord.Forbidden:
        await ctx.send("I don't have permission to mute/unmute that member.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

@client.command()
@has_allowed_role()
async def unmute(ctx, user: discord.Member):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send("You don't have permission to unmute members.")
        return
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        await ctx.send("Muted role not found.")
        return
    if mute_role not in user.roles:
        await ctx.send(f"{user.mention} is not muted.")
        return
    try:
        await user.remove_roles(mute_role)
        await ctx.send(f"{user.mention} has been unmuted.")
    except discord.Forbidden:
        await ctx.send("I don't have permission to unmute that member.")
    except Exception as e:
        await ctx.send(f"Error: {e}")

# ---------------------------
# Warnings System (in-memory)
# ---------------------------
warnings_db = {}

@client.command(name='warn')
@has_allowed_role()
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    guild_id = str(ctx.guild.id)
    warnings_db.setdefault(guild_id, {})
    warnings_db[guild_id].setdefault(member.id, [])
    warnings_db[guild_id][member.id].append({"by": ctx.author.id, "reason": reason, "time": datetime.utcnow().isoformat()})
    await ctx.send(f"{member.mention} has been warned for: {reason}")

@client.command(name='warnings')
async def warnings(ctx, member: discord.Member):
    guild_id = str(ctx.guild.id)
    user_warnings = warnings_db.get(guild_id, {}).get(member.id, [])
    if not user_warnings:
        await ctx.send(f"{member.mention} has no warnings.")
        return
    lines = [f"{idx+1}. {w['reason']} (by <@{w['by']}>)" for idx, w in enumerate(user_warnings)]
    await ctx.send(f"Warnings for {member.mention}:\n" + "\n".join(lines))

@client.command(name='clearwarnings')
@has_allowed_role()
async def clear_warnings(ctx, member: discord.Member):
    guild_id = str(ctx.guild.id)
    if guild_id in warnings_db and member.id in warnings_db[guild_id]:
        warnings_db[guild_id][member.id] = []
        await ctx.send(f"Cleared warnings for {member.mention}.")
    else:
        await ctx.send(f"{member.mention} has no warnings to clear.")

@client.command(name='serverwarnings')
@has_allowed_role()
async def server_warnings(ctx):
    guild_id = str(ctx.guild.id)
    guild_warnings = warnings_db.get(guild_id, {})
    if not guild_warnings:
        await ctx.send("There are no warnings in this server.")
        return
    lines = []
    for member_id, warns in guild_warnings.items():
        member = ctx.guild.get_member(member_id)
        name = member.display_name if member else str(member_id)
        lines.append(f"{name} — {len(warns)} warnings")
    await ctx.send("\n".join(lines))

# ---------------------------
# Timezone utility
# ---------------------------
timezone_map = {
    'CST': 'America/Chicago',
    'EST': 'America/New_York',
    'PST': 'America/Los_Angeles',
    'UTC': 'UTC',
    'UTC-6': 'Etc/GMT+6',
    'UTC+6': 'Etc/GMT-6',
}

@client.command()
async def time(ctx, timezone: str = "UTC"):
    tz_input = timezone.upper().strip()
    tz_name = timezone_map.get(tz_input, timezone)
    try:
        tz = pytz.timezone(tz_name)
    except Exception:
        await ctx.send(f"Unknown timezone: {timezone}")
        return
    now = datetime.now(tz)
    await ctx.send(f"Current time in {tz_name}: {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")

# ---------------------------
# Embed helper
# ---------------------------
@client.command()
async def embed(ctx, *, message: str):
    embed = discord.Embed(description=message, color=discord.Color.green())
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)

# ---------------------------
# How to Advertise (kept but adjusted)
# ---------------------------
@client.command()
async def howtoad(ctx):
    embed = discord.Embed(
        title="📢│How to Advertise at RTN Union",
        description=(
            "Welcome to the promo zone! Here's how to get started the right way:\n\n"
            "✅ **STEP 1: Read the Rules**\n"
            "Make sure you’ve read the server rules before posting. No spam, NSFW, or DM advertising.\n\n"
            "✅ **STEP 2: Choose the Right Channel**\n"
            "Post in the category that fits your ad best. Wrong-channel ads will be deleted.\n\n"
            "✅ **STEP 3: Format Your Ad Nicely**\n"
            "A clean ad gets more attention. Include: Server Name, Invite Link, Description, Highlights.\n\n"
            "🔁 **Ad Cooldown:**\n"
            "You may post once every 12–24 hours in a given ad channel. No bumping or reposting early.\n\n"
            "🆘 **Need Help?**\n"
            "Ask a staff member or use the support channel."
        ),
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ---------------------------
# ModMail System
# ---------------------------
@client.event
async def on_message(message):
    # ignore bot messages
    if message.author.bot:
        return

    # handle DM -> create or post to modmail channel
    if isinstance(message.channel, discord.DMChannel):
        guild = client.get_guild(GUILD_ID)
        if guild is None:
            # no guild configured
            await message.channel.send("ModMail is not configured on this bot.")
            return

        category = guild.get_channel(CATEGORY_ID)
        if category is None:
            await message.channel.send("ModMail category not found. Please contact staff.")
            return

        # look for existing channel with topic = user id
        existing = None
        for ch in category.channels:
            try:
                if ch.topic == str(message.author.id):
                    existing = ch
                    break
            except Exception:
                continue

        if existing:
            channel = existing
        else:
            # create a new channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            safe_name = re.sub(r"[^a-z0-9\-]", "", f"modmail-{message.author.name}".lower().replace(" ", "-"))[:90]
            channel = await guild.create_text_channel(
                name=safe_name or f"modmail-{message.author.id}",
                overwrites=overwrites,
                category=category,
                topic=str(message.author.id)
            )
            await channel.send(f"📬 New ModMail opened by **{message.author}** (ID: {message.author.id})")

        # relay the message content and attachments
        content = message.content or "(no text)"
        relay = f"**{message.author} ({message.author.id}):**\n{content}"
        await channel.send(relay)
        # relay attachments if any
        for att in message.attachments:
            await channel.send(att.url)

        return  # don't continue to command processing for DMs

    # allow commands to work normally in guild channels
    await client.process_commands(message)

@client.command()
@commands.has_permissions(manage_messages=True)
async def reply(ctx, *, response: str):
    """Reply to the user who opened the modmail (use inside the modmail channel)."""
    topic = ctx.channel.topic
    if not topic or not topic.isdigit():
        await ctx.send("❌ This is not a ModMail channel (no user ID found in topic).")
        return
    try:
        user = await client.fetch_user(int(topic))
        # send reply
        parts = [f"✉️ **Reply from staff:**\n{response}"]
        await user.send("\n".join(parts))
        await ctx.send(f"✅ Replied to **{user}**.")
    except discord.Forbidden:
        await ctx.send("❌ Could not send the message. The user may have DMs disabled.")
    except Exception as e:
        await ctx.send(f"⚠️ Error: {e}")

@client.command()
@commands.has_permissions(manage_channels=True)
async def close(ctx):
    """Close the modmail ticket (deletes the channel)."""
    topic = ctx.channel.topic
    if not topic or not topic.isdigit():
        await ctx.send("❌ This is not a ModMail channel.")
        return
    try:
        user = await client.fetch_user(int(topic))
        try:
            await user.send("📪 Your ModMail ticket has been closed. If you need help again, feel free to message me.")
        except discord.Forbidden:
            await ctx.send("⚠️ Could not notify the user — DMs may be closed.")
    except Exception:
        pass

    await ctx.send("✅ Closing this ticket...")
    try:
        await ctx.channel.delete()
    except Exception as e:
        await ctx.send(f"Could not delete the channel: {e}")

# ---------------------------
# Giveaways (slash command + simple loop)
# ---------------------------
giveaways = {}  # message_id -> end_time

def parse_time_to_timedelta(time_str: str) -> timedelta:
    match = re.match(r"^(\d+)([smhd])$", time_str.lower())
    if not match:
        raise ValueError("Invalid time format")
    value, unit = match.groups()
    value = int(value)
    if unit == 's':
        return timedelta(seconds=value)
    if unit == 'm':
        return timedelta(minutes=value)
    if unit == 'h':
        return timedelta(hours=value)
    if unit == 'd':
        return timedelta(days=value)
    raise ValueError("Invalid time unit")

@client.tree.command(name="startgiveaway", description="Start a giveaway with a specified duration and title")
@app_commands.describe(duration="Duration like 1m, 1h, 1d", title="Giveaway title")
async def startgiveaway(interaction: discord.Interaction, duration: str, title: str):
    try:
        delta = parse_time_to_timedelta(duration)
    except ValueError:
        await interaction.response.send_message("Invalid duration format. Use 1m, 1h, 1d, etc.", ephemeral=True)
        return

    end_time = datetime.utcnow() + delta
    giveaway_message = await interaction.channel.send(f"🎉 **{title}** 🎉\nReact with 🎉 to join!\nTime remaining: {duration}.")
    giveaways[giveaway_message.id] = end_time
    await giveaway_message.add_reaction("🎉")
    await interaction.response.send_message("Giveaway started.", ephemeral=True)

    # background countdown (non-blocking)
    while datetime.utcnow() < end_time:
        await asyncio.sleep(10)
        # we avoid constant edits to reduce rate-limit risk
    # finalize
    try:
        message = await interaction.channel.fetch_message(giveaway_message.id)
        reaction = discord.utils.get(message.reactions, emoji="🎉")
        if reaction:
            users = await reaction.users().flatten()
            users = [u for u in users if u.id != client.user.id]
            if users:
                winner = random.choice(users)
                await interaction.channel.send(f"🎉 Congratulations {winner.mention}, you won **{title}**!")
            else:
                await interaction.channel.send("No one entered the giveaway.")
        else:
            await interaction.channel.send("No one entered the giveaway.")
    except Exception as e:
        await interaction.channel.send(f"Error finalizing giveaway: {e}")
    finally:
        giveaways.pop(giveaway_message.id, None)

# ---------------------------
# Moderation Slash Commands (kick/ban/mute)
# ---------------------------
@client.tree.command(name="kick", description="Kick a user from the server.")
@app_commands.describe(user="User to kick", reason="Reason for kick")
async def slash_kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("You don't have permission to kick members.", ephemeral=True)
        return
    try:
        await user.kick(reason=reason)
        await interaction.response.send_message(f"Successfully kicked {user.mention} for: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to kick: {e}", ephemeral=True)

@client.tree.command(name="ban", description="Ban a user from the server.")
@app_commands.describe(user="User to ban", reason="Reason for ban")
async def slash_ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("You don't have permission to ban members.", ephemeral=True)
        return
    try:
        await user.ban(reason=reason)
        await interaction.response.send_message(f"Successfully banned {user.mention} for: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to ban: {e}", ephemeral=True)

@client.tree.command(name="mute", description="Mute a user in the server (creates Muted role if needed).")
@app_commands.describe(user="User to mute", reason="Reason to mute")
async def slash_mute(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("You don't have permission to mute members.", ephemeral=True)
        return
    mute_role = await get_or_create_muted_role(interaction.guild)
    if mute_role is None:
        await interaction.response.send_message("Unable to create Muted role.", ephemeral=True)
        return
    try:
        await user.add_roles(mute_role, reason=reason)
        await interaction.response.send_message(f"Muted {user.mention} for: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to mute: {e}", ephemeral=True)

# ---------------------------
# Run
# ---------------------------
if __name__ == "__main__":
    if TOKEN is None:
        print("TOKEN environment variable not set. Exiting.")
        sys.exit(1)
    client.run(TOKEN)
