import os
import io
import json
import time
import asyncio
import tempfile
from threading import Thread

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ───────────────────────── 설정 ─────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
DATA_FILE = os.path.join(BASE, "data.json")

XP_PER_MESSAGE = 5       # 메시지 1개당 경험치
XP_COOLDOWN = 10         # 경험치 쿨타임(초) - 도배 방지
RUBY_PER_LEVEL = 10      # 레벨업 보상: 달성 레벨 x 10 루비 (Lv.2 → +20)


def need_xp(level: int) -> int:
    """해당 레벨에서 다음 레벨까지 필요한 경험치"""
    return level * 50


# ─────────────────── 1. 웹 서버 (Render 유지용) ───────────────────
app = Flask("")


@app.route("/")
def home():
    return "Bot is running!"


def run_web():
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# ───────────────────────── 2. 데이터 저장 ─────────────────────────
# 구조: {"users": {"유저ID": {"xp","level","ruby"}}, "log_channels": {"서버ID": 채널ID}}
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        d = {}
    d.setdefault("users", {})
    d.setdefault("log_channels", {})
    return d


def save_data():
    # 임시파일에 쓰고 교체 → 저장 중 꺼져도 파일이 깨지지 않음
    fd, tmp = tempfile.mkstemp(dir=BASE, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


data = load_data()
last_xp_time = {}  # 쿨타임용 (메모리)


def get_user(user_id: int) -> dict:
    return data["users"].setdefault(str(user_id), {"xp": 0, "level": 1, "ruby": 0})


def add_xp(user_id: int):
    """경험치 추가. 레벨업 하면 (True, 보상루비) 반환"""
    u = get_user(user_id)
    u["xp"] += XP_PER_MESSAGE
    leveled, reward = False, 0
    while u["xp"] >= need_xp(u["level"]):
        u["xp"] -= need_xp(u["level"])
        u["level"] += 1
        reward += u["level"] * RUBY_PER_LEVEL
        leveled = True
    u["ruby"] += reward
    return leveled, reward


# ───────────────────────── 3. 레벨업 이미지 ─────────────────────────
def font(size: int, bold=True):
    name = "font-bold.ttf" if bold else "font-regular.ttf"
    return ImageFont.truetype(os.path.join(ASSETS, name), size)


def rounded_shadow(base, box, radius, fill, outline=None, blur=18, offset=10, alpha=70):
    """그림자가 있는 둥근 사각형 (글래스 카드 느낌)"""
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    x0, y0, x1, y1 = box
    sd.rounded_rectangle((x0, y0 + offset, x1, y1 + offset), radius, fill=(0, 0, 0, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow)
    ImageDraw.Draw(base).rounded_rectangle(box, radius, fill=fill, outline=outline, width=2)


def make_levelup_card(name: str, handle: str, level: int, ruby: int,
                      next_xp: int, avatar_bytes: bytes | None) -> io.BytesIO:
    W, H = 1054, 590
    # 배경: 왼쪽 흰색 → 오른쪽 회색 그라데이션
    bg = Image.new("RGBA", (W, H))
    px = bg.load()
    for x in range(W):
        t = x / W
        c = int(252 - 52 * t)
        for y in range(H):
            px[x, y] = (c, c, c + 2, 255)
    img = bg

    # 캐릭터(저스터웨이) - 왼쪽
    jpath = os.path.join(ASSETS, "justaway.png")
    if os.path.exists(jpath):
        ch = Image.open(jpath).convert("RGBA")
        ch = ch.resize((470, 470), Image.LANCZOS)
        img.alpha_composite(ch, (-10, H - 470 - 15))

    # 글래스 카드
    cx0, cy0, cx1, cy1 = 440, 40, 1020, 550
    rounded_shadow(img, (cx0, cy0, cx1, cy1), 40, fill=(222, 222, 228, 235), outline=(255, 255, 255, 200))
    d = ImageDraw.Draw(img)

    # 프로필 사진 (원형 + 테두리)
    AV = 100
    ax, ay = cx0 + 45, 170
    d.ellipse((ax - 5, ay - 5, ax + AV + 5, ay + AV + 5), fill=(30, 30, 34, 255))
    if avatar_bytes:
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((AV, AV), Image.LANCZOS)
    else:
        av = Image.new("RGBA", (AV, AV), (150, 150, 160, 255))
    mask = Image.new("L", (AV * 4, AV * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AV * 4, AV * 4), fill=255)
    mask = mask.resize((AV, AV), Image.LANCZOS)
    img.paste(av, (ax, ay), mask)

    # LEVEL UP 알약 + 제목 + 핸들
    tx = ax + AV + 25
    d.rounded_rectangle((tx, 160, tx + 100, 186), 13, fill=(20, 20, 24, 255))
    d.text((tx + 50, 173), "LEVEL UP", font=font(13), fill="white", anchor="mm")
    title = f"{name}님이 레벨 업 했어요!"
    tf = font(30)
    while d.textlength(title, font=tf) > (cx1 - tx - 30) and tf.size > 16:
        tf = font(tf.size - 2)
    d.text((tx, 196), title, font=tf, fill=(15, 15, 18, 255))
    d.text((tx, 242), f"@{handle}", font=font(15, False), fill=(120, 120, 128, 255))

    # 정보 박스
    def box(x0, y0, x1, y1, label, value):
        d.rounded_rectangle((x0, y0, x1, y1), 18, fill=(240, 240, 243, 255))
        d.text((x0 + 18, y0 + 16), label, font=font(14, False), fill=(110, 110, 118, 255))
        d.text((x0 + 18, y0 + 40), value, font=font(22), fill=(15, 15, 18, 255))

    L, R, mid = cx0 + 40, cx1 - 40, (cx0 + cx1) // 2
    box(L, 285, mid - 8, 360, "현재 레벨", f"Lv.{level}")
    box(mid + 8, 285, R, 360, "지급 루비", f"+{ruby}")
    box(L, 375, R, 450, "다음 레벨까지", f"{next_xp} EXP")

    # 하단 검정 바
    d.rounded_rectangle((L, 462, R, 520), 22, fill=(18, 18, 22, 255))
    msg = f"{name}님이 Lv.{level}를 달성하셨어요!"
    mf = font(20)
    while d.textlength(msg, font=mf) > (R - L - 30) and mf.size > 12:
        mf = font(mf.size - 1)
    d.text(((L + R) // 2, 491), msg, font=mf, fill="white", anchor="mm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


async def send_levelup(member: discord.Member, fallback_channel, level: int, ruby: int):
    # 등록된 로그 채널이 있으면 거기로, 없으면 메시지가 온 채널로
    ch_id = data["log_channels"].get(str(member.guild.id))
    channel = member.guild.get_channel(ch_id) if ch_id else None
    channel = channel or fallback_channel

    try:
        avatar = await member.display_avatar.replace(size=256, format="png").read()
    except Exception:
        avatar = None

    loop = asyncio.get_running_loop()
    buf = await loop.run_in_executor(
        None, make_levelup_card,
        member.display_name, member.name, level, ruby, need_xp(level), avatar,
    )
    await channel.send(content=member.mention, file=discord.File(buf, "levelup.png"))


# ───────────────────────── 4. 디스코드 봇 ─────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"로그인 완료: {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    now = time.time()
    if now - last_xp_time.get(message.author.id, 0) >= XP_COOLDOWN:
        last_xp_time[message.author.id] = now
        leveled, reward = add_xp(message.author.id)
        save_data()
        if leveled:
            try:
                await send_levelup(message.author, message.channel,
                                   get_user(message.author.id)["level"], reward)
            except Exception as e:
                print("레벨업 이미지 전송 실패:", e)

    await bot.process_commands(message)


@bot.tree.command(name="로그등록", description="레벨업 알림 이미지를 보낼 채널을 지정합니다.")
@app_commands.describe(채널="레벨업 이미지를 받을 채널")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def log_register(interaction: discord.Interaction, 채널: discord.TextChannel):
    perms = 채널.permissions_for(interaction.guild.me)
    if not (perms.send_messages and perms.attach_files):
        await interaction.response.send_message(
            f"{채널.mention} 에 메시지 보내기 / 파일 첨부 권한이 필요해요.", ephemeral=True)
        return
    data["log_channels"][str(interaction.guild.id)] = 채널.id
    save_data()
    await interaction.response.send_message(f"✅ 레벨업 로그 채널을 {채널.mention} 으로 등록했어요!")


@bot.tree.command(name="레벨", description="레벨과 경험치를 확인합니다.")
async def level_command(interaction: discord.Interaction):
    u = get_user(interaction.user.id)
    need = need_xp(u["level"])
    await interaction.response.send_message(
        f"{interaction.user.mention} 님의 레벨: Lv.{u['level']} ({u['xp']}/{need} XP)\n"
        f"다음 레벨까지 {need - u['xp']} XP 필요 · 보유 루비: {u['ruby']}"
    )


# ───────────────────────── 5. 실행 ─────────────────────────
keep_alive()
bot.run(os.environ.get("TOKEN"))
