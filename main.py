"""
Discord Nitro Checker Bot
Python 3.10+
Install: pip install -U discord.py aiohttp

/nitro_check checks ONE user-supplied gift code at a time.
It does not generate codes, brute-force codes, redeem gifts, or send codes to webhooks.

Note: Discord's gift-code lookup route is not a documented public verification API.
It may change, rate-limit requests, or return ambiguous results. A successful lookup
does not guarantee the gift can be redeemed by the current account.
"""

import os
import re
import asyncio
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

CODE_PATTERN = re.compile(r"^[A-Za-z0-9]{16}$")
API_BASE = "https://discord.com/api/v10"
USER_COOLDOWN_SECONDS = 30
_last_check: dict[int, float] = {}


def extract_code(raw: str) -> str | None:
    """Accept a 16-character code or a discord.gift URL."""
    value = raw.strip()

    if "://" in value:
        parsed = urlparse(value)
        if parsed.hostname not in {"discord.gift", "www.discord.gift"}:
            return None
        value = parsed.path.strip("/").split("/")[0]

    elif value.startswith(("discord.gift/", "www.discord.gift/")):
        value = value.split("/", 1)[1].split("?", 1)[0].strip("/")

    # Remove query parameters if a bare URL-like value was supplied.
    value = value.split("?", 1)[0].strip("/")

    return value if CODE_PATTERN.fullmatch(value) else None


async def lookup_gift_code(code: str) -> tuple[str, str]:
    """
    Returns (status, message).
    The endpoint is unofficial and results must be treated cautiously.
    """
    url = (
        f"{API_BASE}/entitlements/gift-codes/{code}"
        "?with_application=false&with_subscription_plan=true"
    )
    headers = {
        "User-Agent": "NitroInfoBot/1.0 (gift-code lookup)",
        "Accept": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=12)

    try:
        async with aiohttp.ClientSession(
            timeout=timeout, headers=headers
        ) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    # A 200 response means Discord returned a gift-code record.
                    # It does not prove the gift is redeemable by this user.
                    if isinstance(data, dict) and data.get("code"):
                        return (
                            "found",
                            "디스코드에서 해당 기프트 코드 정보를 찾았습니다. "
                            "단, 이미 사용됨·만료됨·계정 제한 등의 이유로 "
                            "실제 등록이 불가능할 수 있습니다."
                        )
                    return (
                        "unknown",
                        "응답을 해석할 수 없습니다. 공식 Discord에서 확인해 주세요."
                    )

                if response.status == 404:
                    return (
                        "not_found",
                        "디스코드에서 해당 코드를 찾지 못했습니다. "
                        "코드가 잘못되었거나 존재하지 않을 수 있습니다."
                    )

                if response.status == 429:
                    retry_after = response.headers.get("Retry-After", "잠시")
                    return (
                        "rate_limited",
                        f"디스코드가 요청을 제한했습니다. {retry_after}초 후 다시 시도해 주세요."
                    )

                if response.status in (401, 403):
                    return (
                        "blocked",
                        "디스코드가 조회 요청을 거부했습니다. "
                        "이 결과만으로 코드의 유효성을 판단할 수 없습니다."
                    )

                return (
                    "unknown",
                    f"디스코드에서 예상하지 못한 응답({response.status})을 받았습니다. "
                    "잠시 후 다시 시도하거나 공식 페이지에서 확인해 주세요."
                )

    except asyncio.TimeoutError:
        return "error", "디스코드 응답 시간이 초과되었습니다."
    except aiohttp.ClientError:
        return "error", "디스코드에 연결하지 못했습니다."


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"로그인 완료: {bot.user}")
        print(f"슬래시 명령어 {len(synced)}개 동기화 완료")
    except Exception as error:
        print(f"명령어 동기화 실패: {error}")


@bot.tree.command(name="ping", description="봇 응답 속도를 확인합니다.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"퐁! 응답 속도: **{round(bot.latency * 1000)}ms**",
        ephemeral=True
    )


@bot.tree.command(
    name="nitro_check",
    description="직접 입력한 Discord Nitro 기프트 코드 한 개를 조회합니다."
)
@app_commands.describe(code="16자리 코드 또는 discord.gift 링크")
@app_commands.checks.cooldown(1, USER_COOLDOWN_SECONDS)
async def nitro_check(interaction: discord.Interaction, code: str):
    gift_code = extract_code(code)

    if gift_code is None:
        await interaction.response.send_message(
            "올바른 형식이 아닙니다. 16자리 영문자·숫자 코드 또는 "
            "`https://discord.gift/코드` 형식의 링크를 입력해 주세요.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    status, message = await lookup_gift_code(gift_code)

    colors = {
        "found": discord.Color.green(),
        "not_found": discord.Color.red(),
        "rate_limited": discord.Color.orange(),
        "blocked": discord.Color.orange(),
        "unknown": discord.Color.orange(),
        "error": discord.Color.orange(),
    }
    titles = {
        "found": "기프트 코드 정보 확인됨",
        "not_found": "코드를 찾을 수 없음",
        "rate_limited": "요청 제한",
        "blocked": "조회 거부됨",
        "unknown": "확인 불가",
        "error": "연결 오류",
    }

    embed = discord.Embed(
        title=titles.get(status, "조회 결과"),
        description=message,
        color=colors.get(status, discord.Color.greyple())
    )
    embed.add_field(
        name="중요 안내",
        value=(
            "이 조회는 코드를 사용하거나 등록하지 않습니다. "
            "최종적인 사용 가능 여부는 Discord 공식 앱/웹사이트의 "
            "기프트 등록 화면에서 확인하세요."
        ),
        inline=False
    )
    embed.set_footer(text="코드는 비공개 응답으로 표시되며 봇이 저장하지 않습니다.")
    await interaction.followup.send(embed=embed, ephemeral=True)


@nitro_check.error
async def nitro_check_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"잠시 기다려 주세요. {error.retry_after:.0f}초 후 다시 확인할 수 있습니다."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    else:
        raise error


@bot.tree.command(name="nitro_info", description="Nitro 코드 확인 방법을 안내합니다.")
async def nitro_info(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Discord Nitro 기프트 코드 안내**\n"
        "• 코드는 공식 Discord 앱/웹사이트에서 등록하세요.\n"
        "• 출처가 불분명한 링크에 로그인 정보를 입력하지 마세요.\n"
        "• 봇 조회 결과만으로 실제 등록 가능 여부를 보장할 수 없습니다.\n"
        "• 이 봇은 코드를 생성하거나 자동으로 등록하지 않습니다.",
        ephemeral=True
    )


def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN 환경 변수가 없습니다. "
            "봇 토큰을 환경 변수로 설정한 뒤 실행하세요."
        )
    bot.run(os.environ.get("TOKEN"))


if __name__ == "__main__":
    main()
