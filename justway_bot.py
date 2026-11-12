import asyncio
from datetime import datetime, timedelta, timezone
import os
import socket
import threading
from discord import app_commands
import discord
from discord.ext import commands, tasks

# 한국 표준시(KST: UTC+9) 정의
KST = timezone(timedelta(hours=9))


# 봇이 실행 중인 서버의 IP 주소 가져오기
def get_server_ip():
  try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip
  except:
    return "127.0.0.1"


SERVER_IP = get_server_ip()

# --- 디스코드 봇 코드 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# DM 관련 명령어를 쓸 수 있는 사람 (봇 주인)
OWNER_ID = 1350789101179109408
DM_MAX = 10  # /dm 한 번에 보낼 수 있는 최대 횟수


async def owner_only(interaction: discord.Interaction) -> bool:
  """주인이 아니면 안내 메시지를 보내고 False 반환"""
  if interaction.user.id != OWNER_ID:
    await interaction.response.send_message(
        "⛔ 이 명령어는 봇 주인만 사용할 수 있어요.", ephemeral=True
    )
    return False
  return True


# 모든 예약 목록을 저장할 딕셔너리
reservations = {}

# 같은 분(Minute) 중복 전송 방지용 변수
last_sent_minute = ""


@bot.event
async def on_ready():
  print(f"{bot.user} 로그인 완료 (서버 IP: {SERVER_IP})")
  try:
    synced = await bot.tree.sync()
    print(f"슬래시 커맨드 {len(synced)}개 동기화됨")
  except Exception as e:
    print(e)

  if not check_reservations.is_running():
    check_reservations.start()


@tasks.loop(seconds=20)
async def check_reservations():
  global last_sent_minute
  now_dt = datetime.now(KST)
  current_time = now_dt.strftime("%H:%M")
  current_minute_key = now_dt.strftime("%Y-%m-%d %H:%M")

  if last_sent_minute == current_minute_key:
    return

  for res_key, data in list(reservations.items()):
    if data["time"] == current_time:
      last_sent_minute = current_minute_key
      target = data["target"]
      message = data["message"]
      kind = data["kind"]  # "DM" 또는 "채널"
      repeat = data["repeat"]  # True(매일반복) 또는 False(1회성)

      try:
        await target.send(message)
        repeat_str = "매일반복" if repeat else "1회성"
        print(
            f"[{repeat_str} 예약 성공] [{kind}] {target.name}에게 전송 완료"
            f" (시간: {current_time})"
        )
      except discord.Forbidden:
        print(f"[예약 실패] 대상({target.name})에게 권한이 없어 메시지를 보낼 수 없습니다.")
      except Exception as e:
        print(f"[예약 에러] {e}")

      # 1회성 예약은 발송 후 삭제
      if not repeat:
        del reservations[res_key]


@check_reservations.before_loop
async def before_check_reservations():
  await bot.wait_until_ready()


# --- /말하기 커맨드 ---
@bot.tree.command(
    name="말하기", description="채팅에 지정한 내용을 횟수만큼 반복해서 보냅니다 (최대 50개)"
)
@app_commands.describe(말할내용="봇이 말할 메시지 내용", 보낼량="반복해서 보낼 횟수 (1~50)")
async def speak(interaction: discord.Interaction, 말할내용: str, 보낼량: int):
  print(
      f"\033[92m[명령어 실행] /말하기 | 유저: {interaction.user.name} | 횟수:"
      f" {보낼량}\033[0m"
  )

  if 보낼량 < 1 or 보낼량 > 50:
    await interaction.response.send_message(
        "❌ 보낼량은 1부터 50 사이의 숫자만 입력 가능합니다.", ephemeral=True
    )
    return

  await interaction.response.defer(ephemeral=True)

  for i in range(보낼량):
    try:
      await interaction.channel.send(말할내용)
      await asyncio.sleep(0.3)
    except Exception as e:
      print(f"메시지 전송 에러: {e}")
      break

  await interaction.followup.send(
      f"✅ 성공적으로 총 {보낼량}개의 메시지를 보냈습니다.", ephemeral=True
  )


# --- /dm 커맨드 ---
@bot.tree.command(
    name="dm", description="특정 유저에게 DM 보내기 (주인 전용, 최대 10개)"
)
@app_commands.describe(
    유저="DM을 받을 사람", 보낼량="몇 번 보낼지 (최대 10)", 메시지="보낼 내용"
)
async def dm(
    interaction: discord.Interaction,
    유저: discord.User,
    보낼량: int,
    메시지: str,
):
  if not await owner_only(interaction):
    return
  print(
      f"\033[92m[명령어 실행] /dm | 유저: {interaction.user.name} | 대상:"
      f" {유저.name} | 횟수: {보낼량}\033[0m"
  )

  if 보낼량 < 1 or 보낼량 > DM_MAX:
    await interaction.response.send_message(
        f"❌ 보낼량은 1부터 {DM_MAX} 사이의 숫자만 입력 가능합니다.", ephemeral=True
    )
    return

  await interaction.response.defer(ephemeral=True)

  success_count = 0

  for i in range(보낼량):
    try:
      await 유저.send(메시지)
      success_count += 1
      await asyncio.sleep(1.0)
    except discord.Forbidden:
      print(f"DM 전송 실패: {유저.name}님에게 DM을 보낼 수 없습니다.")
      break
    except Exception as e:
      print(f"기타 에러 발생: {e}")
      break

  await interaction.followup.send(
      f"완료: {success_count}번 보냄", ephemeral=True
  )


# --- /dm예약 커맨드 (DM 1회성 예약) ---
@bot.tree.command(
    name="dm예약", description="지정한 시간에 특정 유저에게 DM을 1회 예약 전송합니다"
)
@app_commands.describe(
    보낼사람="DM을 받을 사람",
    보낼시간="보낼 시간 (예: 14:30 형식의 24시간제)",
    메시지="보낼 내용",
)
async def dm_reservation(
    interaction: discord.Interaction,
    보낼사람: discord.User,
    보낼시간: str,
    메시지: str,
):
  if not await owner_only(interaction):
    return
  try:
    datetime.strptime(보낼시간, "%H:%M")
  except ValueError:
    await interaction.response.send_message(
        "❌ 시간 형식은 `HH:MM` (예: `14:30` 또는 `09:15`) 형식으로 입력해주세요.",
        ephemeral=True,
    )
    return

  res_key = f"dm_once_{interaction.user.id}_{보낼사람.id}"
  reservations[res_key] = {
      "target": 보낼사람,
      "time": 보낼시간,
      "message": 메시지,
      "kind": "DM",
      "repeat": False,
  }

  await interaction.response.send_message(
      f"⏰ **[DM 1회성 예약 등록]**\n- 대상: @{보낼사람.name}\n- 시간: {보낼시간} (한국"
      f" 시간)\n- 내용: {메시지}",
      ephemeral=True,
  )


# --- /dm매일예약 커맨드 (DM 매일 반복 예약) ---
@bot.tree.command(
    name="dm매일예약",
    description="매일 지정한 시간에 특정 유저에게 DM을 반복 전송합니다",
)
@app_commands.describe(
    보낼사람="DM을 받을 사람",
    보낼시간="보낼 시간 (예: 14:30 형식의 24시간제)",
    메시지="보낼 내용",
)
async def dm_daily_reservation(
    interaction: discord.Interaction,
    보낼사람: discord.User,
    보낼시간: str,
    메시지: str,
):
  if not await owner_only(interaction):
    return
  try:
    datetime.strptime(보낼시간, "%H:%M")
  except ValueError:
    await interaction.response.send_message(
        "❌ 시간 형식은 `HH:MM` (예: `14:30` 또는 `09:15`) 형식으로 입력해주세요.",
        ephemeral=True,
    )
    return

  res_key = f"dm_daily_{interaction.user.id}_{보낼사람.id}"
  reservations[res_key] = {
      "target": 보낼사람,
      "time": 보낼시간,
      "message": 메시지,
      "kind": "DM",
      "repeat": True,
  }

  await interaction.response.send_message(
      f"🔄 **[DM 매일 반복 예약 등록]**\n- 대상: @{보낼사람.name}\n- 매일 시간:"
      f" {보낼시간} (한국 시간)\n- 내용: {메시지}",
      ephemeral=True,
  )


# --- /dm예약취소 커맨드 ---
@bot.tree.command(name="dm예약취소", description="등록된 DM 예약을 취소합니다")
@app_commands.describe(취소할사람="예약을 취소할 대상 유저")
async def cancel_dm_reservation(
    interaction: discord.Interaction, 취소할사람: discord.User
):
  once_key = f"dm_once_{interaction.user.id}_{취소할사람.id}"
  daily_key = f"dm_daily_{interaction.user.id}_{취소할사람.id}"

  canceled = False
  if once_key in reservations:
    del reservations[once_key]
    canceled = True
  if daily_key in reservations:
    del reservations[daily_key]
    canceled = True

  if canceled:
    await interaction.response.send_message(
        f"✅ @{취소할사람.name}님에게 등록된 DM 예약이 취소되었습니다.",
        ephemeral=True,
    )
  else:
    await interaction.response.send_message(
        f"❌ @{취소할사람.name}님으로 설정된 활성 DM 예약이 없습니다.",
        ephemeral=True,
    )


# --- /채널예약 커맨드 (채널 1회성 예약) ---
@bot.tree.command(
    name="채널예약",
    description="지정한 시간에 특정 채널에 메시지를 1회 예약 전송합니다",
)
@app_commands.describe(
    보낼채널="메시지가 전송될 텍스트 채널",
    보낼시간="보낼 시간 (예: 14:30 형식의 24시간제)",
    메시지="보낼 내용",
)
async def channel_reservation(
    interaction: discord.Interaction,
    보낼채널: discord.TextChannel,
    보낼시간: str,
    메시지: str,
):
  try:
    datetime.strptime(보낼시간, "%H:%M")
  except ValueError:
    await interaction.response.send_message(
        "❌ 시간 형식은 `HH:MM` (예: `14:30` 또는 `09:15`) 형식으로 입력해주세요.",
        ephemeral=True,
    )
    return

  res_key = f"channel_once_{interaction.user.id}_{보낼채널.id}"
  reservations[res_key] = {
      "target": 보낼채널,
      "time": 보낼시간,
      "message": 메시지,
      "kind": "채널",
      "repeat": False,
  }

  await interaction.response.send_message(
      f"⏰ **[채널 1회성 예약 등록]**\n- 채널: #{보낼채널.name}\n- 시간: {보낼시간}"
      f" (한국 시간)\n- 내용: {메시지}",
      ephemeral=True,
  )


# --- /채널매일예약 커맨드 (채널 매일 반복 예약) ---
@bot.tree.command(
    name="채널매일예약",
    description="매일 지정한 시간에 특정 텍스트 채널에 메시지를 반복 전송합니다",
)
@app_commands.describe(
    보낼채널="메시지가 전송될 텍스트 채널",
    보낼시간="보낼 시간 (예: 14:30 형식의 24시간제)",
    메시지="보낼 내용",
)
async def channel_daily_reservation(
    interaction: discord.Interaction,
    보낼채널: discord.TextChannel,
    보낼시간: str,
    메시지: str,
):
  try:
    datetime.strptime(보낼시간, "%H:%M")
  except ValueError:
    await interaction.response.send_message(
        "❌ 시간 형식은 `HH:MM` (예: `14:30` 또는 `09:15`) 형식으로 입력해주세요.",
        ephemeral=True,
    )
    return

  res_key = f"channel_daily_{interaction.user.id}_{보낼채널.id}"
  reservations[res_key] = {
      "target": 보낼채널,
      "time": 보낼시간,
      "message": 메시지,
      "kind": "채널",
      "repeat": True,
  }

  await interaction.response.send_message(
      f"🔄 **[채널 매일 반복 예약 등록]**\n- 채널: #{보낼채널.name}\n- 매일 시간:"
      f" {보낼시간} (한국 시간)\n- 내용: {메시지}",
      ephemeral=True,
  )


# --- /채널예약취소 커맨드 ---
@bot.tree.command(name="채널예약취소", description="등록된 채널 예약을 취소합니다")
@app_commands.describe(취소할채널="예약을 취소할 텍스트 채널")
async def cancel_channel_reservation(
    interaction: discord.Interaction, 취소할채널: discord.TextChannel
):
  once_key = f"channel_once_{interaction.user.id}_{취소할채널.id}"
  daily_key = f"channel_daily_{interaction.user.id}_{취소할채널.id}"

  canceled = False
  if once_key in reservations:
    del reservations[once_key]
    canceled = True
  if daily_key in reservations:
    del reservations[daily_key]
    canceled = True

  if canceled:
    await interaction.response.send_message(
        f"✅ #{취소할채널.name} 채널의 예약이 취소되었습니다.", ephemeral=True
    )
  else:
    await interaction.response.send_message(
        f"❌ #{취소할채널.name} 채널로 설정된 활성 예약이 없습니다.", ephemeral=True
    )


# --- /예약목록 커맨드 (통합 검색) ---
@bot.tree.command(
    name="예약목록", description="내가 등록한 모든 예약 목록(1회성/반복)을 확인합니다"
)
async def list_reservations(interaction: discord.Interaction):
  user_prefix = f"_{interaction.user.id}_"
  my_reservations = [
      (key, data) for key, data in reservations.items() if user_prefix in key
  ]

  if not my_reservations:
    await interaction.response.send_message(
        "❌ 등록된 활성 예약이 없습니다.", ephemeral=True
    )
    return

  msg = "📋 **[내가 등록한 전체 예약 목록]**\n"
  for i, (key, data) in enumerate(my_reservations, 1):
    kind = data["kind"]
    repeat_type = "매일반복" if data["repeat"] else "1회성"
    target_name = (
        f"@{data['target'].name}"
        if kind == "DM"
        else f"#{data['target'].name}"
    )

    msg += (
        f"\n**{i}.** [{kind} - {repeat_type}] 대상: {target_name} | 시간:"
        f" `{data['time']}` | 내용: {data['message']}"
    )

  await interaction.response.send_message(msg, ephemeral=True)
