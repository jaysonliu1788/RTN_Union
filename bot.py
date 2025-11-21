import discord
from discord.ext import commands
from discord import PermissionOverwrite
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
STAFF_SERVER_ID = int(os.getenv("STAFF_SERVER_ID"))
MODMAIL_CATEGORY_ID = int(os.getenv("MODMAIL_CATEGORY_ID"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ----------------------------
# OWNER-ONLY CHECK
# ----------------------------
def is_owner():
    async def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)


# ----------------------------
# STARTUP
# ----------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# ----------------------------
# USER → SENDS DM TO BOT
# ----------------------------
@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return

    # If it's a DM, create a modmail ticket in staff server
    if isinstance(message.channel, discord.DMChannel):
        await handle_modmail(message)
        return

    await bot.process_commands(message)


# ----------------------------
# FUNCTION: HANDLE MODMAIL
# ----------------------------
async def handle_modmail(message):
    guild = bot.get_guild(STAFF_SERVER_ID)
    if guild is None:
        return

    category = guild.get_channel(MODMAIL_CATEGORY_ID)
    if category is None:
        return

    # Channel name format
    channel_name = f"modmail-{message.author.id}"

    # Check if a ticket already exists
    existing = discord.utils.get(category.channels, name=channel_name)
    if existing:
        await existing.send(f"📩 **New message from {message.author}:**\n{message.content}")
        return

    # CHANNEL PERMISSIONS (everyone can see)
    overwrites = {
        guild.default_role: PermissionOverwrite(view_channel=True, send_messages=False),
        guild.get_member(message.author.id): PermissionOverwrite(view_channel=True, send_messages=True),
        guild.get_role(STAFF_ROLE_ID): PermissionOverwrite(view_channel=True, send_messages=True)
    }

    # Create channel
    channel = await category.create_text_channel(
        name=channel_name,
        overwrites=overwrites,
        topic=f"Modmail ticket for {message.author} ({message.author.id})"
    )

    await channel.send(f"📬 **Modmail opened by {message.author}**\nMessage: {message.content}")

    await message.author.send(
        "📨 Your message has been sent to staff. They will reply here."
    )


# ----------------------------
# STAFF → REPLY IN TICKET
# ----------------------------
@bot.command()
async def reply(ctx, *, msg):
    """Reply to user from the modmail channel."""
    if not ctx.channel.name.startswith("modmail-"):
        return await ctx.reply("This command only works inside ticket channels.")

    user_id = int(ctx.channel.name.split("-")[1])
    user = await bot.fetch_user(user_id)

    await user.send(f"📣 **Staff reply:** {msg}")
    await ctx.send(f"✅ Message sent to {user}")


# ----------------------------
# OWNER COMMANDS
# ----------------------------
@bot.command()
@is_owner()
async def shutdown(ctx):
    await ctx.send("🛑 Shutting down…")
    await bot.close()


@bot.command()
@is_owner()
async def restart(ctx):
    await ctx.send("🔄 Restarting…")
    await bot.close()
    # PM2 or systemd will auto-restart it on Raspberry Pi


bot.run(TOKEN)
