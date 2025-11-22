import discord
from discord.ext import commands
from discord import PermissionOverwrite
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ---------------------------
# CONFIG (inside code)
# ---------------------------
STAFF_SERVER_ID = 1438617538874441781
MODMAIL_CATEGORY_ID = 1438618584627810405
OWNER_ID = 822530323505741834
STAFF_ROLE_ID = 1434738274269794376

PREFIX = "!"
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


# OWNER CHECK
def is_owner():
    async def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)


@bot.event
async def on_ready():
    print(f"[LOGGED IN] {bot.user} is now online.")
    print("Modmail bot running.")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        await create_or_forward_ticket(message)
        return

    await bot.process_commands(message)


async def create_or_forward_ticket(message):
    guild = bot.get_guild(STAFF_SERVER_ID)
    if guild is None:
        return

    category = guild.get_channel(MODMAIL_CATEGORY_ID)
    if category is None:
        return

    username = message.author.name.replace(" ", "-").lower()
    channel_name = f"modmail-{username}-{message.author.id}"

    existing_channel = discord.utils.get(category.channels, name=channel_name)
    if existing_channel:
        await existing_channel.send(
            f"📩 **New message from {message.author}:**\n{message.content}"
        )
        return

    # FIXED PERMISSIONS
    overwrites = {
        guild.default_role: PermissionOverwrite(view_channel=True, send_messages=False),
        guild.get_role(STAFF_ROLE_ID): PermissionOverwrite(view_channel=True, send_messages=True),
    }

    channel = await category.create_text_channel(
        name=channel_name,
        overwrites=overwrites,
        topic=f"Modmail ticket for {message.author} ({message.author.id})"
    )

    await channel.send(
        f"📬 **Modmail opened by {message.author}**\n"
        f"Message: {message.content}"
    )

    await message.author.send(
        "📨 Your message has been delivered to RTN Union Staff. They will respond here."
    )


@bot.command()
async def reply(ctx, *, message_text):
    if not ctx.channel.name.startswith("modmail-"):
        return await ctx.send("❌ This command can only be used in modmail channels.")

    parts = ctx.channel.name.split("-")
    user_id = int(parts[-1])
    user = await bot.fetch_user(user_id)

    await user.send(f"📣 **Staff Reply:** {message_text}")
    await ctx.send("✅ Reply sent.")


@bot.command()
async def close(ctx):
    if not ctx.channel.name.startswith("modmail-"):
        return await ctx.send("❌ This command can only be used in modmail channels.")

    await ctx.send("🗑 Closing this ticket in 3 seconds...")
    await discord.utils.sleep_until(discord.utils.utcnow() + discord.utils.timedelta(seconds=3))
    await ctx.channel.delete()


@bot.command()
@is_owner()
async def shutdown(ctx):
    await ctx.send("🛑 Shutting down bot...")
    await bot.close()


@bot.command()
@is_owner()
async def restart(ctx):
    await ctx.send("🔄 Restarting bot...")
    await bot.close()


bot.run(TOKEN)
