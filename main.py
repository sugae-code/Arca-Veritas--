import discord  # type: ignore
from discord.ext import commands  # type: ignore
from discord import app_commands  # type: ignore
import asyncio
import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv  # type: ignore
from runner_db import RunnerDatabase  # type: ignore # ギルド共通ランナーDB
import sys  # ← 追加！

# .envからトークン読み込み
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.members = True

# --- インスタンス生成 ---
runner_db = RunnerDatabase()
guild_tasks = {}  # {guild_id: {"1h": Task, "2min": Task}}

# --- Bot定義 ---
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='/', intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("スラッシュコマンドが同期されました。")

bot = MyBot()

# --- 画像生成・送信処理 ---
async def post_image(channel, image_path, script_name, server, event_id, guild_id):
    try:
        # 生成コマンド実行
        command = [sys.executable, script_name, str(server), str(guild_id)]
        if event_id:
            command.append(str(event_id))
        subprocess.run(command, check=True)

        # Discordへ送信
        with open(image_path, "rb") as f:
            await channel.send(file=discord.File(f))
        print(f"✅ 画像送信完了: {image_path}")

        # --- 不要ファイル削除 ---
        base = image_path.replace(".png", "")
        html = f"{base}.html"
        pdf = f"{base}.pdf"
        images_dir = f"{base}.images"

        for fpath in [html, pdf, image_path]:
            if os.path.exists(fpath):
                os.remove(fpath)
                print(f"🗑️ 削除: {fpath}")

        if os.path.isdir(images_dir):
            import shutil
            shutil.rmtree(images_dir)
            print(f"🗑️ フォルダ削除: {images_dir}")

    except Exception as e:
        print(f"❌ 画像投稿エラー（{guild_id}）: {e}")

# --- 投稿ループ（1時間ごと） ---
async def post_image_task_1(channel, server, event_id, guild_id):
    while not bot.is_closed():
        now = datetime.now()
        next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        await asyncio.sleep((next_time - now).total_seconds())
        path = f"data/output/t10_1h_{guild_id}.png"
        await post_image(channel, path, "h1.py", server, event_id, guild_id)

# --- 投稿ループ（2分ごと） ---
async def post_image_task_2(channel, server, event_id, guild_id):
    while not bot.is_closed():
        now = datetime.now()
        next_min = (now.minute // 2 + 1) * 2
        next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1) if next_min >= 60 else now.replace(minute=next_min, second=0, microsecond=0)
        await asyncio.sleep((next_time - now).total_seconds())
        path = f"data/output/t10_2min_{guild_id}.png"
        await post_image(channel, path, "min2.py", server, event_id, guild_id)

# --- /setrunner ---
@bot.tree.command(name='setrunner', description='メインランナーを設定（IDと名前）')
async def set_runner(interaction: discord.Interaction, player_id: int, runner_name: str):
    guild_id = interaction.guild_id
    runner_db.set_runner(guild_id, player_id, runner_name)
    await interaction.response.send_message(f"メインランナーを {runner_name} (ID: {player_id}) に設定しました。")

# --- /getrunner ---
@bot.tree.command(name='getrunner', description='現在のメインランナーを表示')
async def get_runner(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    info = runner_db.get_runner(guild_id)
    if info:
        await interaction.response.send_message(f"現在のメインランナーは {info['runner_name']} (ID: {info['user_id']}) です。")
    else:
        await interaction.response.send_message("メインランナーは未設定です。")

# --- /t10-1h 開始 ---
@bot.tree.command(name='t10-1h', description='時速の計算を開始')
async def start_1h(interaction: discord.Interaction, server: int, event_id: str = None):
    guild_id = interaction.guild_id

    # すでに走っていたらキャンセル
    if guild_id in guild_tasks and "1h" in guild_tasks[guild_id]:
        await interaction.response.send_message("⚠️ 時速タスクはすでに実行中です。")
        return

    channel = interaction.channel
    task = bot.loop.create_task(post_image_task_1(channel, server, event_id, guild_id))
    guild_tasks.setdefault(guild_id, {})["1h"] = task
    await interaction.response.send_message("✅ 時速の計算を開始します")

# --- /t10-2min 開始 ---
@bot.tree.command(name='t10-2min', description='2分速の計算を開始')
async def start_2min(interaction: discord.Interaction, server: int, event_id: str = None):
    guild_id = interaction.guild_id

    # すでに走っていたらキャンセル
    if guild_id in guild_tasks and "2min" in guild_tasks[guild_id]:
        await interaction.response.send_message("⚠️ 2分速タスクはすでに実行中です。")
        return

    channel = interaction.channel
    task = bot.loop.create_task(post_image_task_2(channel, server, event_id, guild_id))
    guild_tasks.setdefault(guild_id, {})["2min"] = task
    await interaction.response.send_message("✅ 2分速の計算を開始します")

# --- 停止コマンド ---
@bot.tree.command(name='stopt10-1h', description='時速の計算を停止')
async def stop_1h(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id in guild_tasks and "1h" in guild_tasks[guild_id]:
        guild_tasks[guild_id]["1h"].cancel()
        del guild_tasks[guild_id]["1h"]
        await interaction.response.send_message("時速の計算を停止しました")
    else:
        await interaction.response.send_message("タスクは実行中ではありません")

@bot.tree.command(name='stopt10-2min', description='2分速の計算を停止')
async def stop_2min(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id in guild_tasks and "2min" in guild_tasks[guild_id]:
        guild_tasks[guild_id]["2min"].cancel()
        del guild_tasks[guild_id]["2min"]
        await interaction.response.send_message("2分速の計算を停止しました。")
    else:
        await interaction.response.send_message("タスクは実行中ではありません")

# --- /support ---
@bot.tree.command(name='support', description='コマンド一覧表示')
async def support(interaction: discord.Interaction):
    msg = """
**コマンド一覧**
/setrunner <ID> <名前> : ランナー設定
/getrunner : 現在のランナー確認
/t10-1h <server> [event_id] : 時速の計算を開始
/t10-2min <server> [event_id] : 2分速の計算を開始
/stopt10-1h : 時速の計算を停止
/stopt10-2min : 2分速の計算を停止
"""
    await interaction.response.send_message(msg)

@bot.event
async def on_ready():
    print(f"Botログイン完了: {bot.user.name} ({bot.user.id})")

bot.run(TOKEN)




