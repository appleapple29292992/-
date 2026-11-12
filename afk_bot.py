import os
import discord
from discord import app_commands
from discord.ext import commands

# 본인 디스코드 유저 ID
MY_USER_ID = 1350789101179109408

# 2. 디스코드 봇 설정 (PRESENCE INTENT 필수)
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.presences = True  # 오프라인 상태 감지용

bot = commands.Bot(command_prefix="!", intents=intents)

# 본인 전용 부재중 메시지 저장 변수
my_afk_message = None


@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"슬래시 명령어 {len(synced)}개 동기화 완료")
    except Exception as e:
        print(e)


# 3. /부재중 명령어 (본인만 사용 가능)
@bot.tree.command(
    name="부재중", description="오프라인일 때 보낼 부재중 메시지를 설정합니다."
)
@app_commands.describe(말="설정할 부재중 메시지")
async def set_afk(interaction: discord.Interaction, 말: str):
    global my_afk_message

    # 명령어를 입력한 사람이 본인이 아닌 경우 동작 방지
    if interaction.user.id != MY_USER_ID:
        await interaction.response.send_message(
            "이 봇의 주인만 부재중 메시지를 설정할 수 있습니다.", ephemeral=True
        )
        return

    my_afk_message = 말
    await interaction.response.send_message(
        f"부재중 메시지가 설정되었습니다: **\"{말}\"**\n(오프라인 상태에서 멘션받으면 반응합니다.)",
        ephemeral=True,
    )


# 4. 멘션 감지 및 본인 오프라인 여부 체크 후 답장
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 메시지에 멘션이 포함되어 있고, 부재중 메시지가 등록되어 있는 경우
    if message.mentions and my_afk_message:
        for mentioned_user in message.mentions:
            # 멘션된 대상이 '나'이고, 실제 디스코드 상태가 '오프라인' 또는 '자리 비움'인 경우
            if mentioned_user.id == MY_USER_ID:
                if (
                    mentioned_user.status == discord.Status.offline
                    or mentioned_user.status == discord.Status.idle
                ):
                    await message.reply(
                        f"{message.author.mention}님, 현재 **{mentioned_user.name}**님은 오프라인 상태입니다.\n> 사유: {my_afk_message}"
                    )
                    break

    await bot.process_commands(message)
