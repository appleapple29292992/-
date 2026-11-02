
import os
import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from threading import Thread

# 1. 간단한 웹 서버 생성 (Render가 잠들지 않도록 유지용)
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# 2. 디스코드 봇 설정
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_data = {}
XP_PER_MESSAGE = 5

def add_xp(user_id):
    if user_id not in user_data:
        user_data[user_id] = {"xp": 0, "level": 1}
    data = user_data[user_id]
    data["xp"] += XP_PER_MESSAGE
    leveled_up = False
    while data["xp"] >= data["level"] * 50:
        data["xp"] -= data["level"] * 50
        data["level"] += 1
        leveled_up = True
    return leveled_up

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"로그인 완료: {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    leveled_up = add_xp(message.author.id)
    if leveled_up:
        data = user_data[message.author.id]
        await message.channel.send(f"{message.author.mention} {data['level']}레벨 달성!")
    await bot.process_commands(message)

@bot.tree.command(name="레벨", description="레벨과 경험치를 확인합니다.")
async def level_command(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id not in user_data:
        user_data[user_id] = {"xp": 0, "level": 1}
    data = user_data[user_id]
    need = data["level"] * 50
    await interaction.response.send_message(
        f"{interaction.user.mention} 님의 레벨: {data['level']}lv ({data['xp']})\n다음 레벨까지 {need - data['xp']} XP 필요"
    )

# 3. 웹 서버와 봇 동시 실행
keep_alive()
bot.run(os.environ.get("TOKEN"))
