import os
import io
import json
import time
import asyncio
import tempfile
from threading import Thread
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ───────────────────────── 설정 ─────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
# 이미지/폰트가 main.py 옆에 있으면 거기서, 아니면 assets 폴더에서 찾음
ASSETS = BASE if os.path.exists(os.path.join(BASE, "justaway.png")) else os.path.join(BASE, "assets")
DATA_FILE = os.path.join(BASE, "data.json")

DEFAULT_XP = 5           # /봇설정 으로 바꾸기 전 기본값: 채팅 1번당 경험치
DEFAULT_COOLDOWN = 0     # 경험치 쿨타임(초). 0이면 메시지마다 바로 오름
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
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        d = {}
    d.setdefault("users", {})
    d.setdefault("log_channels", {})
    d.setdefault("settings", {})
    return d


def save_data():
    fd, tmp = tempfile.mkstemp(dir=BASE, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)


data = load_data()
last_xp_time = {}


def get_user(user_id: int) -> dict:
    u = data["users"].setdefault(str(user_id), {"xp": 0, "level": 1, "ruby": 0})
    u.setdefault("ruby", 0)
    return u


def guild_settings(guild_id: int) -> dict:
    return data["settings"].setdefault(str(guild_id), {})


def xp_per_message(guild_id: int) -> int:
    return guild_settings(guild_id).get("xp_per_message", DEFAULT_XP)


def xp_cooldown(guild_id: int) -> int:
    return guild_settings(guild_id).get("cooldown", DEFAULT_COOLDOWN)


def apply_xp(user_id: int, amount: int):
    """경험치 증감(음수 가능). (이전레벨, 현재레벨, 보상루비) 반환"""
    u = get_user(user_id)
    old = u["level"]
    u["xp"] += amount
    reward = 0
    while u["xp"] >= need_xp(u["level"]):          # 레벨 업
        u["xp"] -= need_xp(u["level"])
        u["level"] += 1
        reward += u["level"] * RUBY_PER_LEVEL
    while u["xp"] < 0:                              # 레벨 다운 (제거 시)
        if u["level"] <= 1:
            u["xp"] = 0
            break
        u["level"] -= 1
        u["xp"] += need_xp(u["level"])
    u["ruby"] += reward
    return old, u["level"], reward


# ───────────────────────── 3. 이미지 카드 ─────────────────────────
def font(size: int, bold=True):
    name = "font-bold.ttf" if bold else "font-regular.ttf"
    return ImageFont.truetype(os.path.join(ASSETS, name), size)


def fit_font(d, text, max_w, size, min_size=12, bold=True):
    f = font(size, bold)
    while d.textlength(text, font=f) > max_w and f.size > min_size:
        f = font(f.size - 1, bold)
    return f


def rounded_shadow(base, box, radius, fill, outline=None, blur=18, offset=10, alpha=70):
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + offset, x1, y1 + offset), radius, fill=(0, 0, 0, alpha))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(base).rounded_rectangle(box, radius, fill=fill, outline=outline, width=2)


CX0, CY0, CX1, CY1 = 440, 40, 1020, 550   # 오른쪽 글래스 카드 영역
L, R = CX0 + 40, CX1 - 40                 # 카드 안쪽 좌우 여백
MID = (CX0 + CX1) // 2


def card_frame(name, handle, avatar_bytes, pill_text, title, header_y):
    """배경 + 저스터웨이 + 글래스 카드 + 프로필/제목 헤더"""
    W, H = 1054, 590
    img = Image.new("RGBA", (W, H))
    px = img.load()
    for x in range(W):
        c = int(252 - 52 * x / W)
        for y in range(H):
            px[x, y] = (c, c, c + 2, 255)

    jpath = os.path.join(ASSETS, "justaway.png")
    if os.path.exists(jpath):
        ch = Image.open(jpath).convert("RGBA").resize((470, 470), Image.LANCZOS)
        img.alpha_composite(ch, (-10, H - 470 - 15))

    rounded_shadow(img, (CX0, CY0, CX1, CY1), 40, fill=(222, 222, 228, 235), outline=(255, 255, 255, 200))
    d = ImageDraw.Draw(img)

    AV = 100
    ax, ay = CX0 + 45, header_y + 10
    d.ellipse((ax - 5, ay - 5, ax + AV + 5, ay + AV + 5), fill=(30, 30, 34, 255))
    if avatar_bytes:
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((AV, AV), Image.LANCZOS)
    else:
        av = Image.new("RGBA", (AV, AV), (150, 150, 160, 255))
    mask = Image.new("L", (AV * 4, AV * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AV * 4, AV * 4), fill=255)
    img.paste(av, (ax, ay), mask.resize((AV, AV), Image.LANCZOS))

    tx = ax + AV + 25
    pf = font(13)
    pw = int(d.textlength(pill_text, font=pf)) + 36
    d.rounded_rectangle((tx, header_y, tx + pw, header_y + 26), 13, fill=(20, 20, 24, 255))
    d.text((tx + pw // 2, header_y + 13), pill_text, font=pf, fill="white", anchor="mm")
    d.text((tx, header_y + 36), title, font=fit_font(d, title, CX1 - tx - 30, 30, 16), fill=(15, 15, 18, 255))
    d.text((tx, header_y + 82), f"@{handle}", font=font(15, False), fill=(120, 120, 128, 255))
    return img, d


def info_box(d, x0, y0, x1, y1, label, value):
    d.rounded_rectangle((x0, y0, x1, y1), 18, fill=(240, 240, 243, 255))
    d.text((x0 + 18, y0 + 16), label, font=font(14, False), fill=(110, 110, 118, 255))
    d.text((x0 + 18, y0 + 40), value, font=font(22), fill=(15, 15, 18, 255))


def to_png(img) -> io.BytesIO:
    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG")
    out.seek(0)
    return out


def make_levelup_card(name, handle, level, ruby, next_xp, avatar_bytes):
    img, d = card_frame(name, handle, avatar_bytes, "LEVEL UP", f"{name}님이 레벨 업 했어요!", 160)
    info_box(d, L, 285, MID - 8, 360, "현재 레벨", f"Lv.{level}")
    info_box(d, MID + 8, 285, R, 360, "지급 루비", f"+{ruby}")
    info_box(d, L, 375, R, 450, "다음 레벨까지", f"{next_xp} EXP")
    d.rounded_rectangle((L, 462, R, 520), 22, fill=(18, 18, 22, 255))
    msg = f"{name}님이 Lv.{level}를 달성하셨어요!"
    d.text(((L + R) // 2, 491), msg, font=fit_font(d, msg, R - L - 30, 20), fill="white", anchor="mm")
    return to_png(img)


def make_rank_card(name, handle, level, xp, ruby, avatar_bytes):
    need = need_xp(level)
    remain = need - xp
    img, d = card_frame(name, handle, avatar_bytes, "MY LEVEL", f"{name}님의 레벨", 75)
    info_box(d, L, 205, MID - 8, 280, "현재 레벨", f"Lv.{level}")
    info_box(d, MID + 8, 205, R, 280, "보유 루비", f"{ruby}")
    info_box(d, L, 292, MID - 8, 367, "현재 경험치", f"{xp} / {need}")
    info_box(d, MID + 8, 292, R, 367, "남은 경험치", f"{remain} EXP")

    pct = max(0.0, min(1.0, xp / need))
    d.text((L, 383), "레벨 진행도", font=font(14, False), fill=(110, 110, 118, 255))
    d.text((R, 383), f"{int(pct * 100)}%", font=font(14), fill=(15, 15, 18, 255), anchor="ra")
    d.rounded_rectangle((L, 408, R, 436), 14, fill=(200, 200, 207, 255))
    fw = int((R - L) * pct)
    if fw > 0:
        d.rounded_rectangle((L, 408, L + max(fw, 28), 436), 14, fill=(18, 18, 22, 255))

    d.rounded_rectangle((L, 462, R, 520), 22, fill=(18, 18, 22, 255))
    msg = f"Lv.{level + 1}까지 {remain} EXP 남았어요!"
    d.text(((L + R) // 2, 491), msg, font=fit_font(d, msg, R - L - 30, 20), fill="white", anchor="mm")
    return to_png(img)


async def fetch_avatar(member):
    try:
        return await member.display_avatar.replace(size=256, format="png").read()
    except Exception:
        return None


async def render(func, *args):
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


async def send_levelup(member: discord.Member, fallback_channel, level: int, reward: int):
    ch_id = data["log_channels"].get(str(member.guild.id))
    channel = (member.guild.get_channel(ch_id) if ch_id else None) or fallback_channel
    avatar = await fetch_avatar(member)
    buf = await render(make_levelup_card, member.display_name, member.name,
                       level, reward, need_xp(level) - get_user(member.id)["xp"], avatar)
    await channel.send(content=member.mention, file=discord.File(buf, "levelup.png"))


# ───────────────────────── 4. 디스코드 봇 ─────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.manage_guild


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"로그인 완료: {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    # 채팅만 쳐도 경험치가 오르는 부분
    if message.author.bot or not message.guild:
        return

    gid = message.guild.id
    now = time.time()
    if now - last_xp_time.get(message.author.id, 0) >= xp_cooldown(gid):
        last_xp_time[message.author.id] = now
        old, new, reward = apply_xp(message.author.id, xp_per_message(gid))
        save_data()
        if new > old:
            try:
                await send_levelup(message.author, message.channel, new, reward)
            except Exception as e:
                print("레벨업 이미지 전송 실패:", e)

    await bot.process_commands(message)


@bot.tree.command(name="로그등록", description="레벨업 알림 이미지를 보낼 채널을 지정합니다.")
@app_commands.describe(채널="레벨업 이미지를 받을 채널")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def log_register(interaction: discord.Interaction, 채널: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("서버 관리 권한이 필요해요.", ephemeral=True)
        return
    perms = 채널.permissions_for(interaction.guild.me)
    if not (perms.send_messages and perms.attach_files):
        await interaction.response.send_message(
            f"{채널.mention} 에 메시지 보내기 / 파일 첨부 권한이 필요해요.", ephemeral=True)
        return
    data["log_channels"][str(interaction.guild.id)] = 채널.id
    save_data()
    await interaction.response.send_message(f"✅ 레벨업 로그 채널을 {채널.mention} 으로 등록했어요!")


@bot.tree.command(name="봇설정", description="채팅 1번당 오르는 경험치량 등을 설정합니다. (값 없이 쓰면 현재 설정 확인)")
@app_commands.describe(한채팅당_오를_경험치량="채팅 1번당 오를 경험치 (1~1000)",
                       쿨타임_초="경험치가 다시 오르기까지 기다리는 시간(초). 0이면 매 메시지마다 오름")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def bot_settings(interaction: discord.Interaction,
                       한채팅당_오를_경험치량: Optional[app_commands.Range[int, 1, 1000]] = None,
                       쿨타임_초: Optional[app_commands.Range[int, 0, 600]] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("서버 관리 권한이 필요해요.", ephemeral=True)
        return
    s = guild_settings(interaction.guild.id)
    if 한채팅당_오를_경험치량 is not None:
        s["xp_per_message"] = 한채팅당_오를_경험치량
    if 쿨타임_초 is not None:
        s["cooldown"] = 쿨타임_초
    save_data()
    title = "⚙️ 현재 설정" if 한채팅당_오를_경험치량 is None and 쿨타임_초 is None else "✅ 설정을 저장했어요"
    await interaction.response.send_message(
        f"{title}\n"
        f"• 채팅 1번당 경험치: **{xp_per_message(interaction.guild.id)} XP**\n"
        f"• 경험치 쿨타임: **{xp_cooldown(interaction.guild.id)}초**")


async def _change_xp(interaction, member: discord.Member, amount: int):
    if not is_admin(interaction):
        await interaction.response.send_message("서버 관리 권한이 필요해요.", ephemeral=True)
        return
    if member.bot:
        await interaction.response.send_message("봇에게는 쓸 수 없어요.", ephemeral=True)
        return
    old, new, reward = apply_xp(member.id, amount)
    save_data()
    u = get_user(member.id)
    sign = "추가" if amount > 0 else "제거"
    await interaction.response.send_message(
        f"✅ {member.mention} 님에게 경험치 **{abs(amount)} XP {sign}**\n"
        f"현재 Lv.{new} ({u['xp']}/{need_xp(new)} XP)")
    if new > old:   # 추가하다가 레벨업 한 경우 이미지도 보내줌
        try:
            await send_levelup(member, interaction.channel, new, reward)
        except Exception as e:
            print("레벨업 이미지 전송 실패:", e)


@bot.tree.command(name="경험치_추가", description="유저에게 경험치를 추가합니다. (양수만)")
@app_commands.describe(추가할_사람="경험치를 줄 사람", 량="추가할 경험치 (양수만)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def xp_add(interaction: discord.Interaction, 추가할_사람: discord.Member,
                 량: app_commands.Range[int, 1, 1000000]):
    await _change_xp(interaction, 추가할_사람, 량)


@bot.tree.command(name="경험치_제거", description="유저의 경험치를 제거합니다. (음수만, 예: -30)")
@app_commands.describe(제거할_사람="경험치를 뺄 사람", 량="제거할 경험치 (음수만, 예: -30)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def xp_remove(interaction: discord.Interaction, 제거할_사람: discord.Member,
                    량: app_commands.Range[int, -1000000, -1]):
    await _change_xp(interaction, 제거할_사람, 량)


@bot.tree.command(name="레벨", description="레벨과 경험치를 이미지로 확인합니다.")
@app_commands.describe(유저="확인할 사람 (비우면 나)")
@app_commands.guild_only()
async def level_command(interaction: discord.Interaction, 유저: Optional[discord.Member] = None):
    await interaction.response.defer()
    member = 유저 or interaction.user
    u = get_user(member.id)
    avatar = await fetch_avatar(member)
    buf = await render(make_rank_card, member.display_name, member.name,
                       u["level"], u["xp"], u["ruby"], avatar)
    await interaction.followup.send(file=discord.File(buf, "level.png"))


# ───────────────────────── 5. 실행 ─────────────────────────
keep_alive()
bot.run(os.environ.get("TOKEN"))
