import os
import io
import re
import json
import threading
import asyncio
import datetime

import discord
from discord import app_commands
from discord.ext import commands

# ───────────────────────── 데이터 저장 ─────────────────────────
DATA_FILE = "ticket_data.json"
lock = threading.Lock()


def load():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(data):
    with lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def guild_data(data, gid):
    g = data.setdefault(str(gid), {})
    g.setdefault("panels", {})      # 패널 메시지 ID -> {"inside": str, "mentions": [ids]}
    g.setdefault("tickets", {})     # 채널 ID -> {"owner": id, "mentions": [...], "claimed": id|None}
    g.setdefault("counter", 0)
    g.setdefault("log_channel", None)
    g.setdefault("category", None)
    return g


data = load()


# ───────────────────────── 유틸 ─────────────────────────
def is_staff(member: discord.Member, ticket: dict) -> bool:
    if member.guild_permissions.administrator:
        return True
    ids = set(ticket.get("mentions", []))
    return any(r.id in ids for r in member.roles) or member.id in ids


async def make_transcript(channel: discord.TextChannel) -> discord.File:
    lines = [f"# 티켓 기록: #{channel.name}", f"# 서버: {channel.guild.name}", ""]
    async for m in channel.history(limit=None, oldest_first=True):
        t = m.created_at.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
        content = m.content or ""
        if m.embeds and not content:
            content = "[임베드]"
        lines.append(f"[{t:%Y-%m-%d %H:%M:%S}] {m.author} ({m.author.id}): {content}")
        for a in m.attachments:
            lines.append(f"    📎 {a.url}")
    buf = io.BytesIO("\n".join(lines).encode("utf-8"))
    return discord.File(buf, filename=f"transcript-{channel.name}.txt")


async def close_ticket(channel: discord.TextChannel, closer: discord.Member):
    gid = str(channel.guild.id)
    g = guild_data(data, gid)
    ticket = g["tickets"].get(str(channel.id), {})
    owner_id = ticket.get("owner")

    # 기록 저장
    try:
        file = await make_transcript(channel)
        embed = discord.Embed(title="🔒 티켓 종료", color=0xED4245,
                              timestamp=discord.utils.utcnow())
        embed.add_field(name="채널", value=channel.name)
        embed.add_field(name="티켓 주인", value=f"<@{owner_id}>" if owner_id else "알 수 없음")
        embed.add_field(name="닫은 사람", value=closer.mention)
        if ticket.get("claimed"):
            embed.add_field(name="담당자", value=f"<@{ticket.get('claimed')}>")

        log_id = g.get("log_channel")
        log_ch = channel.guild.get_channel(log_id) if log_id else None
        if log_ch:
            await log_ch.send(embed=embed, file=file)

        # 주인에게 DM
        if owner_id:
            owner = channel.guild.get_member(owner_id)
            if owner:
                try:
                    file2 = await make_transcript(channel)
                    await owner.send(f"**{channel.guild.name}** 서버의 티켓이 종료되었습니다.", file=file2)
                except Exception:
                    pass
    except Exception as e:
        print("로그 저장 실패:", e)

    g["tickets"].pop(str(channel.id), None)
    save(data)
    await asyncio.sleep(3)
    await channel.delete(reason=f"티켓 종료 by {closer}")


# ───────────────────────── 뷰(버튼) ─────────────────────────
class ConfirmCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="닫기", style=discord.ButtonStyle.danger, emoji="✅")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🔒 3초 후 티켓을 닫습니다...", view=None)
        await close_ticket(interaction.channel, interaction.user)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="취소되었습니다.", view=None)


class TicketControlView(discord.ui.View):
    """티켓 채널 안의 버튼 (닫기 / 담당하기)"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 닫기", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = guild_data(data, interaction.guild.id)
        ticket = g["tickets"].get(str(interaction.channel.id))
        if not ticket:
            return await interaction.response.send_message("등록되지 않은 티켓입니다.", ephemeral=True)
        if interaction.user.id != ticket["owner"] and not is_staff(interaction.user, ticket):
            return await interaction.response.send_message("티켓을 닫을 권한이 없습니다.", ephemeral=True)
        await interaction.response.send_message("정말 티켓을 닫을까요?", view=ConfirmCloseView(), ephemeral=True)

    @discord.ui.button(label="담당하기", style=discord.ButtonStyle.success,
                       emoji="🙋", custom_id="ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = guild_data(data, interaction.guild.id)
        ticket = g["tickets"].get(str(interaction.channel.id))
        if not ticket:
            return await interaction.response.send_message("등록되지 않은 티켓입니다.", ephemeral=True)
        if not is_staff(interaction.user, ticket):
            return await interaction.response.send_message("스태프만 담당할 수 있습니다.", ephemeral=True)
        if ticket.get("claimed"):
            return await interaction.response.send_message(
                f"이미 <@{ticket['claimed']}> 님이 담당 중입니다.", ephemeral=True)
        ticket["claimed"] = interaction.user.id
        save(data)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"🙋 {interaction.user.mention} 님이 이 티켓을 담당합니다.",
                                color=0x57F287))


class OpenTicketView(discord.ui.View):
    """패널의 '티켓 열기' 버튼"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="티켓 열기", style=discord.ButtonStyle.primary,
                       emoji="🎫", custom_id="ticket:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        g = guild_data(data, guild.id)
        panel = g["panels"].get(str(interaction.message.id))
        if not panel:
            return await interaction.response.send_message(
                "이 패널 정보를 찾을 수 없습니다. 관리자에게 `/티켓`으로 패널을 다시 만들어 달라고 해주세요.",
                ephemeral=True)

        # 중복 티켓 방지
        for cid, t in g["tickets"].items():
            if t["owner"] == user.id and guild.get_channel(int(cid)):
                return await interaction.response.send_message(
                    f"이미 열려있는 티켓이 있어요: <#{cid}>", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        g["counter"] += 1
        num = g["counter"]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              read_message_history=True, attach_files=True,
                                              embed_links=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                  manage_channels=True, read_message_history=True,
                                                  embed_links=True, attach_files=True),
        }
        pings = []
        for mid in panel["mentions"]:
            target = guild.get_role(mid) or guild.get_member(mid)
            if target:
                overwrites[target] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                    attach_files=True, embed_links=True, manage_messages=True)
                pings.append(target.mention)

        category = guild.get_channel(g["category"]) if g.get("category") else None
        if category is None and isinstance(interaction.message.channel, discord.TextChannel):
            category = interaction.message.channel.category

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{num:04d}",
                category=category,
                overwrites=overwrites,
                topic=f"티켓 주인: {user} ({user.id})",
                reason=f"티켓 생성 by {user}",
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "봇에게 '채널 관리' 권한이 없어 티켓을 만들 수 없어요.", ephemeral=True)

        g["tickets"][str(channel.id)] = {
            "owner": user.id,
            "mentions": panel["mentions"],
            "claimed": None,
        }
        save(data)

        embed = discord.Embed(
            title=f"🎫 티켓 #{num:04d}",
            description=panel["inside"],
            color=0x5865F2,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"{user}", icon_url=user.display_avatar.url)

        await channel.send(
            content=f"{user.mention} {' '.join(pings)}",
            embed=embed,
            view=TicketControlView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        await interaction.followup.send(f"✅ 티켓이 생성되었어요: {channel.mention}", ephemeral=True)


# ───────────────────────── 봇 ─────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # 기록(transcript)에 메시지 내용을 담기 위해 필요


class TicketBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(OpenTicketView())
        self.add_view(TicketControlView())
        await self.tree.sync()
        print("슬래시 커맨드 동기화 완료")


bot = TicketBot()


@bot.event
async def on_ready():
    print(f"로그인: {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game("🎫 티켓 문의"))


# ───────────────────────── 슬래시 커맨드 ─────────────────────────
@bot.tree.command(name="티켓", description="티켓 패널을 만듭니다 (관리자 전용)")
@app_commands.rename(channel="채널", title="티켓글", inside="티켓안글")
@app_commands.describe(
    channel="티켓 패널을 보낼 채널",
    title="패널에 표시될 글 (예: 티켓을 열려면 아래를 누르세요)",
    inside="티켓 안에 표시될 글 (예: @seller @admin 부재중일 수 있으니 기다려주세요)",
)
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def ticket_panel(interaction: discord.Interaction, channel: discord.TextChannel,
                       title: str, inside: str):
    # inside에 들어있는 역할/유저 멘션을 추출 → 티켓 채널 접근 권한 + 핑
    mentions = [int(x) for x in re.findall(r"<@&(\d+)>", inside)]
    mentions += [int(x) for x in re.findall(r"<@!?(\d+)>", inside)]

    embed = discord.Embed(title="🎫 티켓", description=title, color=0x5865F2)
    embed.set_footer(text=interaction.guild.name)

    try:
        msg = await channel.send(embed=embed, view=OpenTicketView())
    except discord.Forbidden:
        return await interaction.response.send_message(
            f"{channel.mention} 채널에 메시지를 보낼 권한이 봇에게 없어요.", ephemeral=True)

    g = guild_data(data, interaction.guild.id)
    g["panels"][str(msg.id)] = {"inside": inside, "mentions": list(set(mentions))}
    save(data)
    await interaction.response.send_message(f"✅ {channel.mention} 에 티켓 패널을 만들었어요!", ephemeral=True)


@bot.tree.command(name="티켓설정", description="로그 채널과 티켓 카테고리를 설정합니다 (관리자 전용)")
@app_commands.rename(log="로그채널", category="카테고리")
@app_commands.describe(log="티켓 기록이 저장될 채널", category="티켓 채널이 만들어질 카테고리")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def ticket_setting(interaction: discord.Interaction,
                         log: discord.TextChannel = None,
                         category: discord.CategoryChannel = None):
    g = guild_data(data, interaction.guild.id)
    if log:
        g["log_channel"] = log.id
    if category:
        g["category"] = category.id
    save(data)
    log_txt = f"<#{g['log_channel']}>" if g["log_channel"] else "없음"
    cat = interaction.guild.get_channel(g["category"]) if g["category"] else None
    cat_txt = f"**{cat.name}**" if cat else "패널 채널 기준"
    await interaction.response.send_message(
        f"✅ 설정 완료\n로그 채널: {log_txt}\n카테고리: {cat_txt}", ephemeral=True)


def get_ticket_or_none(interaction: discord.Interaction):
    g = guild_data(data, interaction.guild.id)
    return g["tickets"].get(str(interaction.channel.id))


@bot.tree.command(name="유저추가", description="이 티켓에 유저를 추가합니다 (스태프 전용)")
@app_commands.rename(member="유저")
@app_commands.guild_only()
async def add_user(interaction: discord.Interaction, member: discord.Member):
    ticket = get_ticket_or_none(interaction)
    if not ticket:
        return await interaction.response.send_message("티켓 채널에서만 사용할 수 있어요.", ephemeral=True)
    if not is_staff(interaction.user, ticket):
        return await interaction.response.send_message("스태프만 사용할 수 있어요.", ephemeral=True)
    await interaction.channel.set_permissions(member, view_channel=True, send_messages=True,
                                              read_message_history=True, attach_files=True)
    await interaction.response.send_message(f"➕ {member.mention} 님을 티켓에 추가했어요.")


@bot.tree.command(name="유저제거", description="이 티켓에서 유저를 제거합니다 (스태프 전용)")
@app_commands.rename(member="유저")
@app_commands.guild_only()
async def remove_user(interaction: discord.Interaction, member: discord.Member):
    ticket = get_ticket_or_none(interaction)
    if not ticket:
        return await interaction.response.send_message("티켓 채널에서만 사용할 수 있어요.", ephemeral=True)
    if not is_staff(interaction.user, ticket):
        return await interaction.response.send_message("스태프만 사용할 수 있어요.", ephemeral=True)
    if member.id == ticket["owner"]:
        return await interaction.response.send_message("티켓 주인은 제거할 수 없어요.", ephemeral=True)
    await interaction.channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"➖ {member.mention} 님을 티켓에서 제거했어요.")


@bot.tree.command(name="티켓이름", description="이 티켓의 채널 이름을 변경합니다 (스태프 전용)")
@app_commands.rename(name="이름")
@app_commands.guild_only()
async def rename_ticket(interaction: discord.Interaction, name: str):
    ticket = get_ticket_or_none(interaction)
    if not ticket:
        return await interaction.response.send_message("티켓 채널에서만 사용할 수 있어요.", ephemeral=True)
    if not is_staff(interaction.user, ticket):
        return await interaction.response.send_message("스태프만 사용할 수 있어요.", ephemeral=True)
    await interaction.response.send_message(f"✏️ 이름을 `{name}` 으로 변경합니다.")
    await interaction.channel.edit(name=name)


@bot.tree.command(name="티켓닫기", description="이 티켓을 닫습니다")
@app_commands.guild_only()
async def close_cmd(interaction: discord.Interaction):
    ticket = get_ticket_or_none(interaction)
    if not ticket:
        return await interaction.response.send_message("티켓 채널에서만 사용할 수 있어요.", ephemeral=True)
    if interaction.user.id != ticket["owner"] and not is_staff(interaction.user, ticket):
        return await interaction.response.send_message("티켓을 닫을 권한이 없어요.", ephemeral=True)
    await interaction.response.send_message("정말 티켓을 닫을까요?", view=ConfirmCloseView(), ephemeral=True)


# ───────────────────────── 에러 처리 ─────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "⛔ 관리자만 사용할 수 있는 명령어예요."
    else:
        msg = "오류가 발생했어요. 잠시 후 다시 시도해주세요."
        print("커맨드 오류:", error)
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
