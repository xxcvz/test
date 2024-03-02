import discord
from discord.ext import tasks, commands
import praw
import re
import os, asyncio
from youtubesearchpython import VideosSearch
from yt_dlp import YoutubeDL
import openai
import time
import random
import json
import datetime as dt
import pytz

intents = discord.Intents.all()
intents.messages = True
intents.message_content = True
intents.voice_states = True
intents.members = True
bot = commands.Bot(command_prefix=">", intents=intents, case_insensitive=True)  # Set case_insensitive to True


# Ensure the guild queues directory exists
GUILD_QUEUES_DIRECTORY = "guild_queues"
os.makedirs(GUILD_QUEUES_DIRECTORY, exist_ok=True)
guild_music_queues = {}
# A dictionary to store mod roles for each guild
guild_mod_roles = {}
is_playing = False
is_paused = False
vc = None

last_youtube_request_time = 0
youtube_request_interval = 5
reddit_url_base = "https://www.reddit.com"


# Load existing guild queues on bot start
for filename in os.listdir(GUILD_QUEUES_DIRECTORY):
    if filename.endswith(".json"):
        guild_id = int(filename[:-5])  # Extract guild ID from the filename
        with open(os.path.join(GUILD_QUEUES_DIRECTORY, filename), "r") as file:
            guild_music_queues[guild_id] = json.load(file)
    
os.makedirs(GUILD_QUEUES_DIRECTORY, exist_ok=True)

# Function to load guild queues from file
def load_guild_queue(guild_id):
    try:
        with open(os.path.join(GUILD_QUEUES_DIRECTORY, f"{guild_id}.json"), "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return []
    
# Function to save guild queues to file
def save_guild_queue(guild_id):
    with open(os.path.join(GUILD_QUEUES_DIRECTORY, f"{guild_id}.json"), "w") as file:
        json.dump(guild_music_queues[guild_id], file)
    

bot.remove_command('help')

subreddit_name = "tf2"
search_strings = ["cheat", "bot", "hack", "hoster"]
openai.api_key = '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'
ASK_COOLDOWN = 10
ask_command_cooldown = commands.CooldownMapping.from_cooldown(1, ASK_COOLDOWN, commands.BucketType.user)


MAX_EMBED_CHARACTERS = 2048

@bot.command(name="ask", brief="Ask a question to AI")
@commands.cooldown(1, ASK_COOLDOWN, commands.BucketType.user)
async def ask(ctx, *, question):
    # Check if the command is on cooldown
    remaining_time = ask_command_cooldown.update_rate_limit(ctx.message)
    if remaining_time:
        # Command is on cooldown
        embed = discord.Embed(
            title="Cooldown",
            description=f"This command is on cooldown. Please wait {remaining_time:.1f} seconds before trying again.",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return

    # Generate a response from ChatGPT
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": question},
        ],
    )["choices"][0]["message"]["content"]

    # Mention the author and send the response in an embed
    author_mention = ctx.author.mention

    # Split the response into chunks if it exceeds the maximum character limit
    response_chunks = [response[i:i+MAX_EMBED_CHARACTERS] for i in range(0, len(response), MAX_EMBED_CHARACTERS)]

    for i, chunk in enumerate(response_chunks, start=1):
        embed = discord.Embed(
            title="AI Response",
            description=f"{author_mention}, here is the response (Part {i}/{len(response_chunks)}):",
            color=0x3498db
        )
        embed.add_field(name="Question", value=question, inline=False)
        embed.add_field(name="Response", value=chunk, inline=False)

        # Send the embed back to the user
        await ctx.send(embed=embed)


music_queue = []
YDL_OPTIONS = {'format': 'bestaudio/best'}
FFMPEG_OPTIONS = {'options': '-vn -bufsize 64k'}



ytdl = YoutubeDL(YDL_OPTIONS)

# File to store processed submission IDs
processed_submissions_file = "processed_submissions.txt"

# Function to load processed submissions from the file
def load_processed_submissions():
    if os.path.exists(processed_submissions_file):
        with open(processed_submissions_file, "r") as file:
            return set(file.read().splitlines())
    return set()

# Function to save processed submissions to the file
def save_processed_submissions(submission_ids):
    with open(processed_submissions_file, "w") as file:
        file.write("\n".join(submission_ids))

# Searching the item on YouTube
def yt_search(item):
    if item.startswith("https://"):
        title = ytdl.extract_info(item, download=False)["title"]
        return {'source': item, 'title': title}
    search = VideosSearch(item, limit=1)
    if search.result():
        return {'source': search.result()["result"][0]["link"], 'title': search.result()["result"][0]["title"]}
    
    time.sleep(2)
    return None



# Function to play the next song
async def play_next(guild_id):
    global is_playing, vc, ytdl

    if len(guild_music_queues[guild_id]) > 0:
        is_playing = True

        m_url = guild_music_queues[guild_id][0][0]['source']
        voice_channel = guild_music_queues[guild_id][0][1]

        # Remove the first element as you are currently playing it
        guild_music_queues[guild_id].pop(0)

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(m_url, download=False))
        song = data['url']

        vc.play(
            discord.FFmpegPCMAudio(song, executable="ffmpeg", **FFMPEG_OPTIONS),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild_id), loop)
        )

        # Save guild queues to file after modifying them
        save_guild_queue(guild_id)
    else:
        is_playing = False


async def play_music(ctx, guild_id):
    global is_playing, vc, ytdl

    if len(guild_music_queues[guild_id]) > 0:
        is_playing = True

        m_url = guild_music_queues[guild_id][0][0]['source']
        voice_channel = guild_music_queues[guild_id][0][1]

        if not vc or not vc.is_connected():
            vc = await voice_channel.connect()

        # Remove the first element as you are currently playing it
        guild_music_queues[guild_id].pop(0)

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(m_url, download=False))
        song = data['url']

        vc.play(
            discord.FFmpegPCMAudio(song, executable="ffmpeg", **FFMPEG_OPTIONS),
            after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild_id), loop)
        )

        # Save guild queues to file after modifying them
        with open(os.path.join(GUILD_QUEUES_DIRECTORY, f"{guild_id}.json"), "w") as file:
            json.dump(guild_music_queues[guild_id], file)
    else:
        is_playing = False



@bot.command(name="coin", brief="Flips a coin (heads or tails)")
async def coin(ctx):
    # Generate a random number (0 or 1) to represent heads or tails
    result = random.choice(["Heads", "Tails"])

    # Create an embedded message
    embed = discord.Embed(
        title="Coin Flip",
        description=f"The coin landed on: {result}",
        color=discord.Color.blue()
    )

    # Send the embedded message
    await ctx.send(embed=embed)

@bot.command(name="dev", brief="Dev notes")
async def complain(ctx):
    embed = discord.Embed(title="Dev notes",
                          description="For some reason the music skips certain parts and stops for no reason\n"
                                      "Instead of pulling my hairs out I've decided that I don't care",
                          color=0xFF5733)  # You can customize the color

    await ctx.send(embed=embed)

    
@bot.command(name="play", brief="Plays a selected song from YouTube")
async def play(ctx, *args):
    global is_playing, vc, guild_music_queues, last_youtube_request_time

    query = " ".join(args)

    try:
        voice_channel = ctx.author.voice.channel
    except AttributeError:
        embed = create_embed("Error", "You need to connect to a voice channel first!", 0xff0000)
        await ctx.send(embed=embed)
        return
	
    guild_id = ctx.guild.id

    
    # Initialize the music queue for the guild if not exists
    if guild_id not in guild_music_queues:
        guild_music_queues[guild_id] = []

    if is_paused:
        vc.resume()
    else:
        # Check if enough time has passed since the last YouTube API request
        current_time = time.time()
        time_since_last_request = current_time - last_youtube_request_time
        if time_since_last_request < youtube_request_interval:
            await asyncio.sleep(youtube_request_interval - time_since_last_request)
        last_youtube_request_time = time.time()

        song = yt_search(query)
        if type(song) == type(True):
            embed = create_embed("Error", "Could not download the song. Incorrect format, try another keyword. This could be due to a playlist or a livestream format.", 0xff0000)
            await ctx.send(embed=embed)
        else:
            if is_playing:
                embed = create_embed("Success", f"**#{len(guild_music_queues[guild_id]) + 2} - '{song['title']}'** added to the queue", 0x00ff00)
            else:
                embed = create_embed("Success", f"**'{song['title']}'** added to the queue", 0x00ff00)

            await ctx.send(embed=embed)

            guild_music_queues[guild_id].append([song, voice_channel])

            if not is_playing:
                try:
                    await play_music(ctx, guild_id)
                except Exception as e:
                    print(f"An error occurred during playback: {e}")

@bot.command(name='rich', brief="You know what she said?")
async def send_video(ctx):
    video_url = "https://cdn.discordapp.com/attachments/1175171569929162882/1197469936814149652/rich.mov?ex=65bb61c8&is=65a8ecc8&hm=5254110edf52ff949e49531dd52efd24cef194ed48824f77af65da5c01ed0872&"
    
    # Send the video URL to the channel where the command was used
    await ctx.send(video_url)
    
@bot.command(name="skip", brief="Skips the current song being played")
async def skip(ctx):
    global vc
    if vc != None and vc:
        vc.stop()
        # try to play next in the queue if it exists
        await play_music(ctx)
        embed = create_embed("Skipped", "The current song has been skipped", 0x00ff00)
        await ctx.send(embed=embed)


# Command to display the current songs in the queue
@bot.command(name="queue", brief="Displays the current songs in queue")
async def queue(ctx):
    guild_id = ctx.guild.id
    guild_queue = guild_music_queues.get(guild_id, [])

    retval = ""
    for i, song in enumerate(guild_queue, start=1):
        retval += f"#{i} - {song['title']}\n"

    if retval != "":
        embed = create_embed("Queue", retval, 0x00ff00)
        await ctx.send(embed=embed)
    else:
        # Updated else block to send the message as an embed
        embed = create_embed("Queue", "No music in queue", 0xff0000)
        await ctx.send(embed=embed)


# Command to clear the guild queue
@bot.command(name="clear", brief="Stops the music and clears the queue")
async def clear(ctx):
    global vc, is_playing, guild_music_queues

    guild_id = ctx.guild.id

    if vc != None and is_playing:
        vc.stop()

    # Clear the guild-specific queue
    guild_music_queues[guild_id] = []

    # Save the updated guild queue to file
    save_guild_queue(guild_id)

    embed = create_embed("Cleared", "Music queue cleared", 0x00ff00)
    await ctx.send(embed=embed)
                         
# Command to stop the music
@bot.command(name="stop", brief="Kick the bot from VC")
async def dc(ctx):
    global vc, is_playing, is_paused, guild_music_queues

    guild_id = ctx.guild.id

    is_playing = False
    is_paused = False

    await vc.disconnect()

    # Clear the guild-specific queue
    guild_music_queues[guild_id] = []

    # Save the updated guild queue to file
    save_guild_queue(guild_id)

    embed = create_embed("Stopped", "The playback has been stopped", 0x00ff00)
    await ctx.send(embed=embed)





# Command to remove the last song from the guild queue
@bot.command(name="remove", brief="Removes last song added to queue")
async def re(ctx):
    global guild_music_queues

    guild_id = ctx.guild.id

    if guild_music_queues[guild_id]:
        guild_music_queues[guild_id].pop()
        save_guild_queue(guild_id)

        embed = create_embed("Removed", "Last song removed from the queue", 0x00ff00)
        await ctx.send(embed=embed)
    else:
        embed = create_embed("Queue", "No music in guild queue", 0xff0000)
        await ctx.send(embed=embed)

reddit = praw.Reddit(
    client_id="PQnh81CjKCAZy_yvyoto4A",
    client_secret="4Bfz9LQ_L1sFD5aytShz_fW6vCXV-Q",
    user_agent="tf2-relay/1.0 by Ok_Culture_4339",
)


@tasks.loop(minutes=10)
async def check_reddit():
    global search_strings
    # Load processed submissions
    processed_submissions = load_processed_submissions()
    subreddit = reddit.subreddit(subreddit_name)
    
    for submission in subreddit.new(limit=10):  # You can adjust the limit as needed
        submission_id = submission.id
        # Check if the submission has been processed before
        if submission_id not in processed_submissions:
            # Check if any search string is present in the title (case-insensitive)
            if any(keyword.lower() in submission.title.lower() for keyword in search_strings):
                # Check if the title contains @everyone or @here using regular expressions
                if not ("@everyone" in submission.title or "@here" in submission.title):
                    # Process the submission
                    channel_id = 1196601528052617319
                    channel = bot.get_channel(channel_id)
                    # Use submission.permalink instead of submission.url
                    message = f"**{submission.title}**\n{reddit_url_base}{submission.permalink}"
                    await channel.send(message)
                    # Mark the submission as processed
                    processed_submissions.add(submission_id)
    # Save the updated processed submissions to the file
    save_processed_submissions(processed_submissions)



@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    # Assign the join and leave channels
    global join_channel, leave_channel
    join_channel = bot.get_channel(join_channel_id)
    leave_channel = bot.get_channel(leave_channel_id)
    if not join_channel or not leave_channel:
        print("Error: One or both channels not found.")
        return
    check_reddit.start()


# Channels for join and leave messages
join_channel_id = 1144735845518147624
leave_channel_id = 1170483874413953024

join_channel = None
leave_channel = None



# Embed formatting function
def create_embed(title, description, color):
    embed = discord.Embed(title=title, description=description, color=color)
    return embed

@bot.command(name="help", brief="Displays general information about the bot.")
async def send_predefined_message(ctx):
    predefined_message = (
        "**TF2GYM discord bot.** v1.9\n\n"
        "Command prefix is >\nView available commands with >commands\n"
        "Report issues on github"
    )

    embed = create_embed("Bot Information", predefined_message, 0x3498db)
    await ctx.send(embed=embed)

@bot.command(name="github", brief="Bot github page.")
async def send_github_link(ctx):
    github_link_message = "https://github.com/NW-Lightweight/tf2gym-bot"

    embed = create_embed("GitHub Link", github_link_message, 0x3498db)
    await ctx.send(embed=embed)

    

# Command to display user information
@bot.command(name="user", brief="Displays info about a user")
async def user_info(ctx, user: discord.Member = None):
    user = user or ctx.author
    embed = discord.Embed(title="User Info", color=user.color if hasattr(user, 'color') else 0x3498db)
    
    # Check if the user has an avatar
    if user.avatar:
        # Use the avatar URL with a specified size
        embed.set_thumbnail(url=user.avatar.url)
    else:
        embed.set_thumbnail(url=user.default_avatar.url)
    
    embed.add_field(name="Username", value=user.name, inline=True)
    embed.add_field(name="Discriminator", value=user.discriminator, inline=True)
    embed.add_field(name="User ID", value=user.id, inline=True)
    embed.add_field(name="Joined Discord", value=user.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
    embed.add_field(name="Joined Server", value=user.joined_at.strftime("%Y-%m-%d %H:%M:%S") if user.joined_at else "N/A", inline=True)
    
    roles = [f"<@&{role.id}>" for role in user.roles]  # Use <@&role_id> to mention roles
    embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="commands", brief="Lists all commands")
async def list_commands(ctx):
    command_list = "\n".join([f"`{command.name}` - {command.brief}" for command in bot.commands])

    embed = create_embed("Available Commands", command_list, 0x3498db)
    await ctx.send(embed=embed)

join_channel_id = 1144735845518147624
leave_channel_id = 1170483874413953024

@bot.event
async def on_member_join(member):
    account_created_at = member.created_at
    account_age = dt.datetime.utcnow().replace(tzinfo=pytz.UTC) - account_created_at

    embed = discord.Embed(title="Member Joined", color=0x00ff00)
    user = await bot.fetch_user(member.id)  # Fetch the user to ensure full data
    embed.add_field(name="User", value=user.mention, inline=False)
    embed.add_field(name="Account Age", value=format_timedelta(account_age))

    # Set the thumbnail using the logic you provided
    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)
    else:
        embed.set_thumbnail(url=user.default_avatar.url)
    
    if account_age < dt.timedelta(weeks=3):
        embed.set_footer(text="⚠️ Warning: This account is relatively new.")

    # Your logging channel ID
    log_channel_id = 1144735845518147624
    log_channel = member.guild.get_channel(log_channel_id)
    await log_channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    duration_in_server = dt.datetime.utcnow().replace(tzinfo=pytz.UTC) - member.joined_at.replace(tzinfo=pytz.UTC)

    embed = discord.Embed(title="Member Left", color=0xff0000)
    user = await bot.fetch_user(member.id)  # Fetch the user to ensure full data
    embed.add_field(name="User", value=user.mention, inline=False)
    embed.add_field(name="Duration in Server", value=format_timedelta(duration_in_server))
    
    # Fetch the roles before the member leaves
    roles = [role.name for role in member.roles]
    embed.add_field(name="Roles", value=", ".join(roles), inline=False)
    
    # Set the thumbnail using the logic you provided
    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)
    else:
        embed.set_thumbnail(url=user.default_avatar.url)
    
    # Your logging channel ID
    log_channel_id = 1170483874413953024
    log_channel = member.guild.get_channel(log_channel_id)
    await log_channel.send(embed=embed)


def format_timedelta(delta):
    days, seconds = delta.days, delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    formatted_time = ""
    if days:
        formatted_time += f"{days} days, "
    if hours:
        formatted_time += f"{hours} hours, "
    if minutes:
        formatted_time += f"{minutes} minutes, "
    formatted_time += f"{seconds} seconds"

    return formatted_time

bot.run("MTE5NjYwMDExNjY5MDMwOTI0Mg.G7T1IS.DdqkvVnnR_8oNLjvKrpu64SeiuwsGGmC6MGQ4M")