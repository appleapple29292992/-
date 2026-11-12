"""
저스터웨이 봇 통합 실행기
- 봇 여러 개를 한 프로세스에서 동시에 실행합니다. (Render 서비스 1개로 충분)
- 환경변수에 토큰이 있는 봇만 실행됩니다.
- 한 봇이 에러로 죽어도 나머지 봇은 계속 실행됩니다.
"""
import os
import asyncio
import importlib
import threading
import traceback

import discord
from flask import Flask

# (표시 이름, 파이썬 파일명(확장자 제외), 토큰 환경변수 이름)
BOTS = [
    ("부재중 봇", "afk_bot", "TOKEN1"),
    ("저스터웨이 (말하기/DM/예약)", "justway_bot", "TOKEN2"),
    ("냥코 티켓 봇", "nyanko_bot", "TOKEN3"),
    ("레벨 봇", "level_bot", "TOKEN4"),
    ("티켓 봇", "ticket_bot", "TICKET_TOKEN"),
]

status: dict[str, str] = {}

# ───────────── Render / 업타임용 웹서버 ─────────────
web = Flask(__name__)


@web.route("/")
def home():
    lines = ["Bots are running!", ""]
    lines += [f"- {name}: {state}" for name, state in status.items()]
    return "<pre>" + "\n".join(lines) + "</pre>"


def run_web():
    port = int(os.environ.get("PORT", 8080))
    web.run(host="0.0.0.0", port=port, use_reloader=False)


# ───────────── 봇 실행 ─────────────
async def run_bot(name: str, bot, token: str):
    status[name] = "starting"
    try:
        status[name] = "running"
        await bot.start(token)
    except discord.LoginFailure:
        status[name] = "토큰 오류"
        print(f"❌ [{name}] 토큰이 올바르지 않습니다. (Reset Token 후 환경변수 확인)")
    except discord.PrivilegedIntentsRequired:
        status[name] = "인텐트 오류"
        print(f"❌ [{name}] Developer Portal에서 Privileged Intents(Presence/Server Members/Message Content)를 켜주세요.")
    except Exception:
        status[name] = "crashed"
        print(f"❌ [{name}] 오류로 종료됨")
        traceback.print_exc()


async def main():
    tasks = []
    for name, module_name, env_name in BOTS:
        token = os.environ.get(env_name)
        if not token:
            print(f"⏭️  [{name}] {env_name} 환경변수가 없어서 건너뜀")
            status[name] = "skipped (토큰 없음)"
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception:
            status[name] = "import 실패"
            print(f"❌ [{name}] 코드를 불러오지 못했어요")
            traceback.print_exc()
            continue
        tasks.append(asyncio.create_task(run_bot(name, module.bot, token)))

    if not tasks:
        print("실행할 봇이 없습니다. 환경변수(TOKEN1~4, TICKET_TOKEN)를 확인하세요.")
        # 웹서버는 계속 살아있도록 대기
        await asyncio.Event().wait()
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(main())
