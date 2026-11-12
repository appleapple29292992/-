import asyncio
import json
import os
import re
import threading
import time
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

from bcsfe import core
from bcsfe.core.game.map import enigma as bc_enigma
from bcsfe.core.game.gamoto import ototo as bc_ototo

core.core_data.init_data()
load_dotenv()

open_tickets: dict[int, int] = {}
ticket_owners: dict[int, int] = {}
ticket_data: dict[int, dict] = {}
finished_tickets: set[int] = set()
# ---------------------------------------------------------------------------
# 봇 기본 설정
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 저스터웨이! 봇 내부 관리자 허용 목록
BOT_OWNER_USER_ID = 1350789101179109408
BOT_ADMIN_USER_IDS = {}
ADMIN_USERS_FILE = "admin_users.json"


def load_added_admin_ids() -> set[int]:
    if not os.path.exists(ADMIN_USERS_FILE):
        return set()

    try:
        with open(ADMIN_USERS_FILE, "r", encoding="utf-8") as file:
            raw_ids = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"{ADMIN_USERS_FILE}을 읽을 수 없습니다. 파일을 확인해주세요."
        ) from error

    if not isinstance(raw_ids, list):
        raise RuntimeError(f"{ADMIN_USERS_FILE} 형식이 올바르지 않습니다.")

    try:
        return {int(user_id) for user_id in raw_ids}
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{ADMIN_USERS_FILE}에 잘못된 사용자 ID가 있습니다.") from error


ADDED_ADMIN_USER_IDS = load_added_admin_ids()


def is_bot_admin(member: discord.abc.User) -> bool:
    return (
        member.id == BOT_OWNER_USER_ID
        or member.id in BOT_ADMIN_USER_IDS
        or member.id in ADDED_ADMIN_USER_IDS
    )


def save_added_admin_ids() -> None:
    with open(ADMIN_USERS_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(ADDED_ADMIN_USER_IDS), file, ensure_ascii=False, indent=2)


MAX_CATFOOD = 2147483647
MAX_XP = 99999999
MAX_I32 = 2147483647

ITEMS = {
    "1": "통조림",
    "2": "경험치(XP)",
    "3": "레어 티켓",
    "4": "플래티넘 티켓",
    "5": "레전드 티켓",
    "6": "냥코 티켓",
    "7": "NP",
    "8": "리더십",
    "9": "플래티넘 조각",
    "10": "캣츠아이",
    "11": "개다래",
    "12": "배틀 아이템",
}

ITEM_MENU_TEXT = (
    "1. 통조림\n"
    "2. 경험치(XP)\n"
    "3. 레어 티켓\n"
    "4. 플래티넘 티켓\n"
    "5. 레전드 티켓\n"
    "6. 냥코 티켓\n"
    "7. NP\n"
    "8. 리더십\n"
    "9. 플래티넘 조각\n"
    "10. 캣츠아이\n"
    "11. 개다래\n"
    "12. 배틀 아이템\n\n"
    "`0또는 취소`를 입력하면 처음으로 돌아가요."
)

SPECIAL_ITEM_NAMES = {"캣츠아이", "개다래", "배틀 아이템"}

ITEM_NAME_TO_ATTR = {
    "통조림": "catfood",
    "경험치(XP)": "xp",
    "레어 티켓": "rare_tickets",
    "플래티넘 티켓": "platinum_tickets",
    "레전드 티켓": "legend_tickets",
    "냥코 티켓": "normal_tickets",
    "NP": "np",
    "리더십": "leadership",
    "플래티넘 조각": "platinum_shards",
}

ATTR_MAX = {
    "catfood": MAX_CATFOOD,
}
DEFAULT_MAX = MAX_XP

MAIN_MENU_TEXT = (
    "1. 아이템\n"
    "2. 캐릭터 획득\n"
    "3. 캐릭터 제거\n"
    "4. 스토리 클리어 / 보물\n"
    "5. 점수 & 콘텐츠\n"
    "6. 콘텐츠 클리어 (좀비/이벤트/강습 등)\n\n"
    "`확인` 을 입력하면 새로운 이어하기 코드와 인증번호를 전송합니다."
)


STORY_CHAPTER_GROUPS = {
    "eoc": [0, 1, 2],
    "itf": [3, 4, 5],
    "cotc": [6, 7, 8],
}
STORY_STAGES_PER_CHAPTER = 48
MAX_TREASURE_LEVEL = 3

STORY_ACTION_LABELS = {
    "eoc_clear": "세계편 클리어",
    "itf_clear": "미래편 클리어",
    "cotc_clear": "우주편 클리어",
    "eoc_treasure": "세계편 최고급 보물",
    "itf_treasure": "미래편 최고급 보물",
    "cotc_treasure": "우주편 최고급 보물",
}
STORY_ACTION_MENU_KEYS = {
    "1": "eoc_clear",
    "2": "itf_clear",
    "3": "cotc_clear",
    "4": "eoc_treasure",
    "5": "itf_treasure",
    "6": "cotc_treasure",
}
STORY_ACTION_MENU_TEXT = (
    "1. 세계편 클리어\n"
    "2. 미래편 클리어\n"
    "3. 우주편 클리어\n"
    "4. 세계편 최고급 보물\n"
    "5. 미래편 최고급 보물\n"
    "6. 우주편 최고급 보물"
)

# --- 점수 & 콘텐츠 ---
MISC_ACTION_LABELS = {
    "challenge_max": "챌린지 점수 MAX",
    "dojo_max": "도장 점수 MAX",
    "dojo_championship_clear": "도장 챔피언십 클리어",
    "itf_timed_max": "ITF 타임어택 MAX",
    "missions_complete": "모든 미션 완료",
    "rank_rewards_claim": "랭크 보상 전부 수령",
}
MISC_ACTION_MENU_KEYS = {
    "1": "challenge_max",
    "2": "dojo_max",
    "3": "dojo_championship_clear",
    "4": "itf_timed_max",
    "5": "missions_complete",
    "6": "rank_rewards_claim",
}
MISC_ACTION_MENU_TEXT = (
    "1. 챌린지 점수 MAX\n"
    "2. 도장 점수 MAX\n"
    "3. 도장 챔피언십 클리어\n"
    "4. ITF 타임어택 MAX\n"
    "5. 모든 미션 완료\n"
    "6. 랭크 보상 전부 수령"
)
NOT_READY_MISC_ACTIONS: set = set()


STAGE_ACTION_LABELS = {
    "zombie_clear": "좀비 전체 클리어",
    "sol_clear": "레전드 스토리(SOL) 전체",
    "event_clear": "이벤트 스테이지 전체",
    "collab_clear": "콜라보 스테이지 전체",
    "gauntlet_clear": "강습(가울렛) 전체",
    "collab_gauntlet_clear": "콜라보 강습 전체",
    "tower_clear": "냥코탑 전체",
    "uncanny_clear": "신 레전드 스토리(Uncanny) 전체",
    "legend_quest_clear": "레전드 퀘스트 전체",
    "zero_legends_clear": "레전드 제로 전체",
    "behemoth_clear": "수수께끼의 초수 토벌 전체",
    "aku_unlock": "마계 편 해방",
    "aku_clear": "마계 편 클리어",
    "catamin_clear": "고양이 드링크 스테이지 전체",
    "enigma_clear": "지하 미궁(Enigma) 클리어",
    "enigma_unlock": "지하 미궁(Enigma) 해방",
    "gamatoto_max": "가마토토 레벨 130",
    "ototo_max": "오토토 개발대 풀강",
}
STAGE_ACTION_MENU_KEYS = {
    "1": "zombie_clear",
    "2": "sol_clear",
    "3": "event_clear",
    "4": "collab_clear",
    "5": "gauntlet_clear",
    "6": "collab_gauntlet_clear",
    "7": "tower_clear",
    "8": "uncanny_clear",
    "9": "legend_quest_clear",
    "10": "zero_legends_clear",
    "11": "behemoth_clear",
    "12": "aku_unlock",
    "13": "aku_clear",
    "14": "catamin_clear",
    "15": "enigma_clear",
    "16": "enigma_unlock",
    "17": "gamatoto_max",
    "18": "ototo_max",
}
STAGE_ACTION_MENU_TEXT = (
    "1. 좀비 전체 클리어\n"
    "2. 레전드 스토리(SOL) 전체\n"
    "3. 이벤트 스테이지 전체\n"
    "4. 콜라보 스테이지 전체\n"
    "5. 강습(가울렛) 전체\n"
    "6. 콜라보 강습 전체\n"
    "7. 냥코탑 전체\n"
    "8. 신 레전드 스토리(Uncanny) 전체\n"
    "9. 레전드 퀘스트 전체\n"
    "10. 레전드 제로 전체\n"
    "11. 수수께끼의 초수 토벌 전체\n"
    "12. 마계 편 해방\n"
    "13. 마계 편 클리어\n"
    "14. 고양이 드링크 스테이지 전체\n"
    "15. 지하 미궁(Enigma) 클리어 (확인 필요)\n"
    "16. 지하 미궁(Enigma) 해방 (확인 필요)\n"
    "17. 가마토토 레벨 130\n"
    "18. 오토토 개발대 풀강"
)
AKU_REALM_STAGE_IDS = [255, 256, 257, 258, 265, 266, 268]


# ---------------------------------------------------------------------------
# 세이브 파일 편집 로직
# ---------------------------------------------------------------------------


class SaveEditError(Exception):
    """세이브 파일 처리 중 사용자에게 보여줄 만한 에러."""


def start_session(
    transfer_code: str, confirmation_code: str, cc_str: str
) -> "core.ServerHandler":
    try:
        cc = core.CountryCode.from_code(cc_str.lower())
    except Exception as e:
        raise SaveEditError(
            f"'{cc_str}'는 알 수 없는 국가 코드예요. en/kr/jp/tw 중 하나를 입력해주세요."
        ) from e

    gv = core.GameVersion(120200)

    server_handler, result = core.ServerHandler.from_codes(
        transfer_code, confirmation_code, cc, gv, print=False
    )
    if server_handler is None:
        raise SaveEditError(
            "이어하기 코드/인증 코드가 올바르지 않거나, 국가 선택이 틀렸거나, "
            "서버 연결에 실패했어요. 코드를 다시 확인해주세요."
        )

    return server_handler


def edit_save_by_codes(
    transfer_code: str,
    confirmation_code: str,
    cc_str: str,
    amounts: dict[str, int],
) -> tuple[str, str]:
    server_handler = start_session(transfer_code, confirmation_code, cc_str)
    save_file = server_handler.save_file

    for attr, value in amounts.items():
        setattr(save_file, attr, value)

    new_codes = server_handler.get_codes()
    if new_codes is None:
        raise SaveEditError(
            "수정된 세이브를 서버에 업로드하지 못했어요. 잠시 후 다시 시도해주세요."
        )

    return new_codes


def max_power_up_cat(save_file: "core.SaveFile", cat: "core.Cat"):
    power_up = core.PowerUpHelper(cat, save_file)
    target_base = power_up.get_max_possible_base() - 1
    target_plus = power_up.get_max_possible_plus()
    upgrade = core.Upgrade(plus=target_plus, base=target_base)
    if upgrade.base != -1:
        power_up.reset_upgrade()
        power_up.upgrade_by(upgrade.base)
    cat.set_upgrade(save_file, upgrade, True)


def max_talents_cat(
    save_file: "core.SaveFile", cat: "core.Cat", ultra_only: bool = False
):
    talent_data = save_file.cats.read_talent_data(save_file)
    if talent_data is None:
        return

    cat_skill = talent_data.get_cat_skill(cat.id)
    if cat_skill is None:
        return

    if cat.talents is None:
        cat.talents = []

    talents_by_id = {talent.id: talent for talent in cat.talents}
    target_limit = 1 if ultra_only else 0
    for skill in cat_skill.skills:
        if skill.ability_id == 0 or skill.limit != target_limit:
            continue

        talent = talents_by_id.get(skill.ability_id)
        if talent is None:
            talent = core.Talent(skill.ability_id, 0)
            cat.talents.append(talent)
            talents_by_id[skill.ability_id] = talent

        talent.level = skill.max_lv if skill.max_lv > 0 else 1


def apply_single_cat_actions(
    save_file: "core.SaveFile", cat: "core.Cat", actions: set[str]
):
    if "remove" in actions:
        cat.remove(reset=True, save_file=save_file)
        return

    cat.unlock(save_file)

    if "maxpower" in actions:
        max_power_up_cat(save_file, cat)

    if "talent_max" in actions:
        max_talents_cat(save_file, cat)

    if "ultra_talent_max" in actions:
        max_talents_cat(save_file, cat, ultra_only=True)

    if "second_form" in actions:
        cat.set_form(1, save_file, set_current_form=True)

    if "true_form" in actions:
        save_file.cats.true_form_cats(
            save_file, [cat], force=False, set_current_forms=True
        )

    if "fourth_form" in actions:
        save_file.cats.fourth_form_cats(
            save_file, [cat], force=False, set_current_forms=True
        )


def apply_cat_actions(save_file: "core.SaveFile", cat_actions: dict):
    if "all" in cat_actions:
        actions = cat_actions["all"]

        if "remove" in actions:
            targets = save_file.cats.get_unlocked_cats() or []
        else:
            targets = save_file.cats.get_cats_obtainable(save_file) or []

        for cat in targets:
            apply_single_cat_actions(save_file, cat, actions)

    cat_actions.pop("all", None)

    for cat_id, actions in cat_actions.items():
        cat = save_file.cats.get_cat_by_id(cat_id)
        if cat is None:
            continue
        apply_single_cat_actions(save_file, cat, actions)


def apply_story_actions(save_file: "core.SaveFile", actions: set):
    if not actions:
        return

    chapters = save_file.story.get_real_chapters()

    def clear_group(chapter_indexes: list[int]):
        for chapter_index in chapter_indexes:
            chapter = chapters[chapter_index]
            for stage_index in range(STORY_STAGES_PER_CHAPTER):
                chapter.clear_stage(stage_index, clear_amount=1)

    def treasure_group(chapter_indexes: list[int]):
        for chapter_index in chapter_indexes:
            chapter = chapters[chapter_index]
            for stage in chapter.get_valid_treasure_stages():
                stage.set_treasure(MAX_TREASURE_LEVEL)

    if "eoc_clear" in actions:
        clear_group(STORY_CHAPTER_GROUPS["eoc"])
    if "itf_clear" in actions:
        clear_group(STORY_CHAPTER_GROUPS["itf"])
    if "cotc_clear" in actions:
        clear_group(STORY_CHAPTER_GROUPS["cotc"])

    if "eoc_treasure" in actions:
        treasure_group(STORY_CHAPTER_GROUPS["eoc"])
    if "itf_treasure" in actions:
        treasure_group(STORY_CHAPTER_GROUPS["itf"])
    if "cotc_treasure" in actions:
        treasure_group(STORY_CHAPTER_GROUPS["cotc"])


def apply_misc_actions(save_file: "core.SaveFile", actions: set):
    if not actions:
        return

    if "challenge_max" in actions:
        challenge = save_file.challenge
        if not challenge.scores:
            challenge.scores = [0]
        challenge.scores[0] = MAX_I32
        challenge.chapters.clear_stage(0, 0, 0, False)

    if "dojo_max" in actions:
        stage = save_file.dojo.chapters.get_stage(0, 0)
        stage.score = MAX_I32

    if "dojo_championship_clear" in actions:
        ranking = save_file.dojo.ranking
        ranking.has_submitted = True
        ranking.has_completed = True
        ranking.has_seen_results = True
        ranking.did_win_rewards = True
        ranking.score = MAX_I32
        ranking.ranking = 1

    if "itf_timed_max" in actions:
        chapters = save_file.story.get_real_chapters()
        max_score = core.core_data.max_value_manager.itf_timed_score
        for chapter_index in STORY_CHAPTER_GROUPS["itf"]:
            chapter = chapters[chapter_index]
            for stage in chapter.get_valid_treasure_stages():
                stage.itf_timed_score = max_score

    if "missions_complete" in actions:
        missions = save_file.missions
        conditions = core.core_data.get_mission_conditions(save_file)
        if conditions.conditions is not None:
            for mission_id in list(missions.clear_states.keys()):
                missions.clear_states[mission_id] = 4
                condition = conditions.conditions.get(mission_id)
                if condition is not None:
                    missions.requirements[mission_id] = condition.progress_count

    if "rank_rewards_claim" in actions:
        rank_gifts = core.core_data.get_rank_gifts(save_file)
        if rank_gifts.rank_gift is not None:
            user_rank = save_file.calculate_user_rank()
            for rank_gift in rank_gifts.rank_gift:
                if rank_gift.threshold <= user_rank:
                    save_file.user_rank_rewards.set_claimed(rank_gift.index, True)


def _clear_gauntlet_style_all(container):
    for map_index, star_group in enumerate(container.chapters):
        for star_index, chapter in enumerate(star_group.chapters):
            total_stages = len(chapter.stages)
            for stage_index in range(total_stages):
                container.clear_stage(
                    map_index,
                    star_index,
                    stage_index,
                    clear_amount=1,
                    overwrite_clear_progress=True,
                    ensure_cleared_only=False,
                )


def _clear_all_outbreaks(save_file: "core.SaveFile"):
    outbreaks = save_file.outbreaks
    for chapter in outbreaks.chapters.values():
        for outbreak in chapter.outbreaks.values():
            outbreak.cleared = True

    for chapter in outbreaks.current_outbreaks.values():
        for outbreak in chapter.outbreaks.values():
            outbreak.cleared = False


def _unlock_aku_realm(save_file: "core.SaveFile"):
    for stage_id in AKU_REALM_STAGE_IDS:
        save_file.event_stages.clear_map(1, stage_id, 0, False)


def _clear_aku_all(save_file: "core.SaveFile"):
    aku = save_file.aku
    if not aku.chapters or not aku.chapters[0].chapters:
        return
    chapter = aku.chapters[0].chapters[0]
    for stage in chapter.stages:
        stage.clear_stage(clear_count=1)


def _unlock_all_enigma_stages(save_file: "core.SaveFile"):
    base_level = 25000
    names = core.MapNames(save_file, "H", base_index=base_level).map_names
    existing_ids = {stage.stage_id for stage in save_file.enigma.stages}
    for map_id in names.keys():
        abs_id = map_id + base_level
        if abs_id in existing_ids:
            continue
        save_file.event_stages.chapter_completion_count[abs_id] = 0
        stage = bc_enigma.Stage(3, abs_id, 2, int(time.time()))
        save_file.enigma.stages.append(stage)


def _max_gamatoto(save_file: "core.SaveFile"):
    gamatoto_levels = core.core_data.get_gamatoto_levels(save_file)
    if gamatoto_levels is None:
        return

    max_level = gamatoto_levels.get_max_level()
    if max_level is None:
        return

    target_level = min(130, max_level)
    xp = gamatoto_levels.get_xp_from_level(target_level)
    if xp is not None:
        save_file.gamatoto.xp = xp


def _max_ototo(save_file: "core.SaveFile"):
    ototo = save_file.ototo
    if ototo.cannons is None:
        ototo.cannons = bc_ototo.Cannons.init(save_file.game_version)

    ototo.engineers = bc_ototo.Ototo.get_max_engineers(save_file)
    recipes = bc_ototo.CastleRecipeUnlock(save_file)
    if recipes.level_part_recipe_unlocks is None:
        return

    for cannon_id, cannon in ototo.cannons.cannons.items():
        cannon.development = 3
        for part_id, _level in enumerate(cannon.levels):
            max_level = recipes.get_max_level(cannon_id, part_id)
            if max_level is None or max_level <= 0:
                continue
            cannon.levels[part_id] = max_level - 1 if part_id == 0 else max_level


def apply_stage_actions(save_file: "core.SaveFile", actions: set):
    if not actions:
        return

    if "zombie_clear" in actions:
        _clear_all_outbreaks(save_file)
    if "sol_clear" in actions:
        save_file.event_stages.clear_group(0, increment=False)
    if "event_clear" in actions:
        save_file.event_stages.clear_group(1, increment=False)
    if "collab_clear" in actions:
        save_file.event_stages.clear_group(2, increment=False)
    if "gauntlet_clear" in actions:
        _clear_gauntlet_style_all(save_file.gauntlets)
    if "collab_gauntlet_clear" in actions:
        _clear_gauntlet_style_all(save_file.collab_gauntlets)
    if "tower_clear" in actions:
        _clear_gauntlet_style_all(save_file.tower.chapters)
    if "uncanny_clear" in actions:
        _clear_gauntlet_style_all(save_file.uncanny.chapters)
    if "legend_quest_clear" in actions:
        _clear_gauntlet_style_all(save_file.legend_quest)
    if "zero_legends_clear" in actions:
        _clear_gauntlet_style_all(save_file.zero_legends)
    if "behemoth_clear" in actions:
        _clear_gauntlet_style_all(save_file.behemoth_culling)
    if "aku_unlock" in actions:
        _unlock_aku_realm(save_file)
    if "aku_clear" in actions:
        _clear_aku_all(save_file)
    if "catamin_clear" in actions:
        _clear_gauntlet_style_all(save_file.catamin_stages.chapters)
    if "enigma_clear" in actions:
        _clear_gauntlet_style_all(save_file.enigma_clears)
    if "enigma_unlock" in actions:
        _unlock_all_enigma_stages(save_file)
    if "gamatoto_max" in actions:
        _max_gamatoto(save_file)
    if "ototo_max" in actions:
        _max_ototo(save_file)


async def finalize_ticket(channel: discord.TextChannel, user_id: int, state: dict):
    amounts: dict[str, int] = {}
    for name, value in state["items"].items():
        attr = ITEM_NAME_TO_ATTR.get(name)
        if attr:
            amounts[attr] = value

    cat_actions: dict = state.get("cat_actions", {})
    special_items: dict[str, int] = state.get("special_items", {})
    story_actions: set = state.get("story_actions", set())
    misc_actions: set = state.get("misc_actions", set())
    stage_actions: set = state.get("stage_actions", set())

    if (
        not amounts
        and not cat_actions
        and not special_items
        and not story_actions
        and not misc_actions
        and not stage_actions
    ):
        await channel.send(
            "적용할 내용이 없어요. 먼저 아이템이나 캐릭터, 스토리, 점수, 콘텐츠 항목을 선택해주세요."
        )
        return

    await channel.send("세이브를 수정해서 업로드하는 중이에요...")

    try:
        server_handler = state["server_handler"]
        save_file = server_handler.save_file

        for attr, value in amounts.items():
            setattr(save_file, attr, value)

        for item_name, amount in special_items.items():
            apply_special_item(save_file, item_name, amount)

        apply_cat_actions(save_file, cat_actions)
        apply_story_actions(save_file, story_actions)
        apply_misc_actions(save_file, misc_actions)
        apply_stage_actions(save_file, stage_actions)

        new_codes = server_handler.get_codes()
        if new_codes is None:
            raise SaveEditError(
                "수정된 세이브를 서버에 업로드하지 못했어요. 잠시 후 다시 시도해주세요."
            )
        new_transfer_code, new_confirmation_code = new_codes

        await channel.send(
            "완료!\n\n"
            f"이어하기 코드: `{new_transfer_code}`\n"
            f"인증코드: `{new_confirmation_code}`\n\n"
            "게임 내 데이터 이전에서 이 코드로 이어하기 해주세요."
        )
        await prompt_close_ticket(channel)
    except SaveEditError as e:
        await channel.send(str(e))
    except Exception:
        traceback.print_exc()
        await channel.send("처리 중 예상치 못한 오류가 발생했어요.")

    ticket_data.pop(user_id, None)


class ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="확인 및 적용",
        style=discord.ButtonStyle.success,
        custom_id="ticket_confirm_and_apply",
    )
    async def confirm_and_apply(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message(
                "티켓 채널에서만 사용할 수 있어요.", ephemeral=True
            )
            return

        owner_id = ticket_owners.get(channel.id)
        if owner_id != interaction.user.id:
            await interaction.response.send_message(
                "이 티켓을 만든 사용자만 확인할 수 있어요.", ephemeral=True
            )
            return

        state = ticket_data.get(interaction.user.id)
        if state is None or state.get("step") != 1:
            await interaction.response.send_message(
                "현재 확인할 변경 내용이 없어요.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "확인됐어요. 세이브를 적용하는 중입니다...", ephemeral=True
        )
        await finalize_ticket(channel, interaction.user.id, state)


def apply_special_item(
    save_file: "core.SaveFile",
    item_name: str,
    amount: int,
):
    if item_name == "캣츠아이":
        save_file.catseyes = [amount] * len(save_file.catseyes)
    elif item_name == "개다래":
        save_file.catfruit = [amount] * len(save_file.catfruit)
    elif item_name == "배틀 아이템":
        for item in save_file.battle_items.items:
            item.amount = amount


def get_cat_display_name(save_file: "core.SaveFile", cat: "core.Cat") -> str:
    names = cat.get_names_cls(save_file)
    return names[0] if names else str(cat.id)


CAT_ACTION_LABELS = {
    "unlock": "추가(해금)",
    "maxpower": "풀강",
    "talent_max": "본능 풀강",
    "ultra_talent_max": "초본능 풀강",
    "second_form": "2진화",
    "true_form": "3진화",
    "fourth_form": "4진화",
}
CAT_ACTION_MENU_KEYS = {
    "1": "unlock",
    "2": "maxpower",
    "3": "talent_max",
    "4": "ultra_talent_max",
    "5": "second_form",
    "6": "true_form",
    "7": "fourth_form",
}
CAT_ACTION_MENU_TEXT = (
    "1. 추가(해금)\n"
    "2. 풀강\n"
    "3. 본능 풀강\n"
    "4. 초본능 풀강\n"
    "5. 2진화\n"
    "6. 3진화\n"
    "7. 4진화"
)


async def get_or_create_closed_category(guild: discord.Guild) -> discord.CategoryChannel:
    closed_category = discord.utils.get(guild.categories, name="티켓-닫힘")
    if closed_category is not None:
        return closed_category
 
    return await guild.create_category(
        "티켓-닫힘",
        overwrites={
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
            ),
        },
    )


async def remove_ticket_owner_access(guild: discord.Guild, owner_id: int):
    member = guild.get_member(owner_id)
    if member is None:
        try:
            member = await guild.fetch_member(owner_id)
        except (discord.NotFound, discord.HTTPException):
            member = None
 
    if member is None:
        member = discord.Object(id=owner_id)
 
    return member


async def close_ticket_channel(
    channel: discord.TextChannel,
    reason: str,
) -> bool:
    finished_tickets.add(channel.id)
    owner_id = ticket_owners.get(channel.id)

    if owner_id is not None:
        try:
            member = await channel.guild.fetch_member(owner_id)
            await channel.set_permissions(member, overwrite=None)
        except (discord.NotFound, discord.HTTPException):
            pass
        open_tickets.pop(owner_id, None)
        ticket_data.pop(owner_id, None)
 
    ticket_owners.pop(channel.id, None)
    finished_tickets.discard(channel.id)

    try:
        await channel.send("티켓이 닫혔어요. 이 채널은 곧 삭제됩니다.")
        await asyncio.sleep(1)
        await channel.delete(reason=reason)
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def prompt_close_ticket(channel: discord.TextChannel):
    finished_tickets.add(channel.id)
    await channel.send(view=CloseButton())
    await asyncio.sleep(300)
    if channel.name.startswith("close-ticket-"):
        return
    await close_ticket_channel(channel, "티켓 자동 종료")


@bot.event
async def on_ready():
    bot.add_view(TicketView())
    bot.add_view(CloseButton())
    bot.add_view(ConfirmView())
    if not getattr(bot, "_slash_commands_synced", False):
        try:
            synced_commands = []
            for guild in bot.guilds:
                bot.tree.copy_global_to(guild=guild)
                synced_commands.extend(await bot.tree.sync(guild=guild))
            bot._slash_commands_synced = True
            print(f"슬래시 명령어 동기화 완료: {len(synced_commands)}개")
        except discord.HTTPException as error:
            print(f"슬래시 명령어 동기화 실패: {error}")
    print(f"로그인 완료: {bot.user} (id={bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if (
        bot.user is not None
        and bot.user in message.mentions
        and isinstance(message.author, discord.Member)
        and is_bot_admin(message.author)
    ):
        embed = discord.Embed(
            title="냥코 티켓",
            description="아래 버튼을 눌러 티켓을 생성하세요.",
            color=0x2ECC71,
        )
        await message.channel.send(embed=embed, view=TicketView())
        return

    if message.channel.id not in open_tickets.values():
        return

    owner_id = ticket_owners.get(message.channel.id)
    if owner_id is not None and message.author.id != owner_id:
        return
    
    owner_channel = open_tickets.get(message.author.id)
    if owner_channel != message.channel.id:
        return

    if message.channel.id in finished_tickets:
        return

    user = message.author
    state = ticket_data.setdefault(
        user.id,
        {
            "step": -1,
            "category": None,
            "transfer_code": "",
            "confirmation_code": "",
            "items": {},
            "selected_item": None,
            "cat_actions": {},
            "special_items": {},
            "cat_mode": None, 
            "story_actions": set(),
            "misc_actions": set(),
            "stage_actions": set(),
        },
    )

    if state["step"] == -1:
        if message.content == "1":
            state["category"] = "이벤트"
        elif message.content == "2":
            state["category"] = "밴 해제"
        else:
            await message.channel.send("1(이벤트) 또는 2(밴 해제) 중 하나를 입력해주세요.")
            return

        state["step"] = 0
        await message.channel.send(
            "옵션 → 계정/기종변경 → 기종변경설정 → 기존단말기에서 이전하기 → "
            "서버에 세이브 데이터를 보존\n\n"
            "**형식**\n"
            "이어하기 코드: abcd1234\n"
            "인증번호: 1234"
        )
        return

    if state["step"] == 0:
        tc = re.search(r"이어하기\s*코드\s*[:：]\s*(\w+)", message.content)
        cc = re.search(r"인증\s*(?:코드|번호)\s*[:：]\s*(\d+)", message.content)

        if not (tc and cc):
            await message.channel.send(
                "형식이 맞지 않아요. 아래처럼 두 줄로 보내주세요.\n"
                "```\n이어하기 코드: abcd1234\n인증번호: 1234\n```"
            )
            return

        await message.channel.send("코드를 확인하는 중이에요...")

        server_handler = None
        last_error: SaveEditError | None = None
        for cc_try in ("kr", "en", "jp", "tw"):
            try:
                server_handler = start_session(tc.group(1), cc.group(1), cc_try)
                break
            except SaveEditError as e:
                last_error = e
                # 서버 방화벽(Rate Limit) 방지를 위해 1초 대기 추가
                await asyncio.sleep(1.0)
                continue
            except Exception:
                traceback.print_exc()
                await message.channel.send(
                    "코드 확인 중 예상치 못한 오류가 발생했어요. 다시 시도해주세요."
                )
                return

        if server_handler is None:
            error_message = str(last_error) if last_error else (
                "이어하기 코드/인증 코드가 올바르지 않거나, 서버 연결에 실패했어요. "
                "코드를 다시 확인해주세요."
            )
            await message.channel.send(f"{error_message}\n\n코드를 다시 입력해주세요.")
            return

        state["server_handler"] = server_handler
        state["transfer_code"] = tc.group(1)
        state["confirmation_code"] = cc.group(1)

        if state["category"] == "밴 해제":
            await message.channel.send("계정 정지 해제를 시도하는 중이에요...")
            try:
                success = server_handler.create_new_account()
                if not success:
                    await message.channel.send(
                        "계정 정지 해제에 실패했어요. 이미 정지 상태가 아니거나, "
                        "서버 쪽 문제일 수 있어요."
                    )
                    ticket_data.pop(user.id, None)
                    return

                new_codes = server_handler.get_codes()
                if new_codes is None:
                    await message.channel.send(
                        "정지 해제는 됐는데, 새 코드를 발급받는 데 실패했어요. "
                        "잠시 후 원래 코드로 다시 시도해보세요."
                    )
                else:
                    new_transfer_code, new_confirmation_code = new_codes
                    await message.channel.send(
                        "계정 정지 해제 완료! 데이터는 그대로 유지된 채 새 계정으로 "
                        "재발급됐어요.\n\n"
                        f"이어하기 코드: `{new_transfer_code}`\n"
                        f"인증코드: `{new_confirmation_code}`\n\n"
                        "게임 내 데이터 이전에서 이 새 코드로 이어하기 해주세요."
                    )
                    await prompt_close_ticket(message.channel)
            except Exception:
                traceback.print_exc()
                await message.channel.send("처리 중 예상치 못한 오류가 발생했어요.")
            ticket_data.pop(user.id, None)
            return

        state["step"] = 1
        await message.channel.send(
            "코드 확인 완료!\n\n" + MAIN_MENU_TEXT + "\n\n",
            view=ConfirmView(),
        )
        return

    if state["step"] == 1:
        if message.content == "1":
            state["step"] = 2
            await message.channel.send(
                "수정할 아이템 번호를 입력해주세요.\n\n" + ITEM_MENU_TEXT
            )
            return
        if message.content == "2":
            state["step"] = 4
            state["cat_mode"] = "acquire"
            await message.channel.send(
                "**[캐릭터 획득]**\n"
                "캐릭터 **ID**를 입력하면 선택되고, **이름**을 입력하면 검색돼요.\n\n"
                "`all`을 입력하면 모든 캐릭터를 얻을 수 있습니다.\n"
                "(0을 입력하면 메인 메뉴로 돌아갑니다.)"
            )
            return
        if message.content == "3":
            state["step"] = 4
            state["cat_mode"] = "remove"
            await message.channel.send(
                "**[캐릭터 제거]**\n"
                "제거할 캐릭터 **ID**를 입력하거나 **이름**으로 검색해주세요.\n\n"
                "`all`을 입력하면 보유 중인 모든 캐릭터를 제거합니다.\n"
                "(0을 입력하면 메인 메뉴로 돌아갑니다.)"
            )
            return
        if message.content == "4":
            state["step"] = 7
            await message.channel.send(
                "**[스토리 클리어 / 보물]**\n"
                "적용할 항목 번호를 입력해주세요. 여러 개면 쉼표로 구분 (예: 1,2,3,4,5,6)\n"
                + STORY_ACTION_MENU_TEXT + "\n\n(0을 입력하면 메인 메뉴로 돌아갑니다.)"
            )
            return
        if message.content == "5":
            state["step"] = 8
            await message.channel.send(
                "**[점수 & 콘텐츠]**\n"
                "적용할 항목 번호를 입력해주세요. 여러 개면 쉼표로 구분 (예: 1,2,3,4,5,6)\n"
                + MISC_ACTION_MENU_TEXT + "\n\n(0을 입력하면 메인 메뉴로 돌아갑니다.)"
            )
            return
        if message.content == "6":
            state["step"] = 9
            await message.channel.send(
                "**[콘텐츠 클리어]**\n"
                "적용할 항목 번호를 입력해주세요. 여러 개면 쉼표로 구분 (예: 1,2,5,7)\n"
                + STAGE_ACTION_MENU_TEXT + "\n\n(0을 입력하면 메인 메뉴로 돌아갑니다.)"
            )
            return
        if message.content == "확인":
            await finalize_ticket(message.channel, user.id, state)
            return

        await message.channel.send(
            "1~6 메뉴를 선택하거나 아래 `확인 및 적용` 버튼을 눌러주세요."
        )
        return

    if state["step"] == 2:
        if message.content in ITEMS:
            item_name = ITEMS[message.content]
            state["selected_item"] = message.content
            state["step"] = 3
            await message.channel.send(f"{item_name} 개수를 입력해주세요. (0 또는 취소 입력시 처음으로)")
            return
        if message.content.strip() in ("0", "취소", "뒤로"):
            state["step"] = 1
            await message.channel.send("항목을 선택해주세요.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
            return
        await message.channel.send("아이템 번호(1~12)를 올바르게 입력해주세요.")
        return

    if state["step"] == 3 and message.content.strip() in ("0", "취소", "뒤로"):
        state["step"] = 2
        state["selected_item"] = None
        await message.channel.send("아이템 선택을 취소했습니다.\n\n" + ITEM_MENU_TEXT)
        return

    if state["step"] == 3:
        if not message.content.isdigit():
            await message.channel.send("숫자만 입력해주세요.")
            return

        item_name = ITEMS[state["selected_item"]]
        amount = int(message.content)

        if item_name in SPECIAL_ITEM_NAMES:
            state.setdefault("special_items", {})[item_name] = amount
        else:
            attr = ITEM_NAME_TO_ATTR.get(item_name)
            limit = ATTR_MAX.get(attr, DEFAULT_MAX)
            if not (0 <= amount <= limit):
                await message.channel.send(f"{item_name}는 0~{limit} 사이로 입력해주세요.")
                return
            state["items"][item_name] = amount

        state["step"] = 1
        await message.channel.send(
            f"{item_name} {amount:,}개 적용됨\n\n항목을 선택해주세요.\n" + MAIN_MENU_TEXT,
            view=ConfirmView(),
        )
        return

    if state["step"] == 4:
        text = message.content.strip()
        cat_mode = state.get("cat_mode", "acquire")

        if text in ("0", "확인", "취소", "뒤로"):
            state["step"] = 1
            state["cat_mode"] = None
            await message.channel.send("항목을 선택해주세요.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
            return

        if not text:
            await message.channel.send("캐릭터 ID를 입력해주세요.")
            return

        save_file = state["server_handler"].save_file

        if text.lower() == "all":
            if cat_mode == "remove":
                state.setdefault("cat_actions", {})["all"] = {"remove"}
                state["step"] = 1
                state["cat_mode"] = None
                await message.channel.send("모든 캐릭터 제거 예약됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
                return
            state["pending_cat_id"] = "all"
            state["pending_cat_name"] = "모든 캐릭터"
            state["step"] = 6
            await message.channel.send("모든 캐릭터 선택됨.\n\n작업 번호를 입력해주세요:\n" + CAT_ACTION_MENU_TEXT)
            return

        if text.isdigit():
            cat_id = int(text)
            cat = save_file.cats.get_cat_by_id(cat_id)
            if cat is None:
                await message.channel.send(f"ID {cat_id} 캐릭터를 찾을 수 없어요.")
                return
            display = get_cat_display_name(save_file, cat)
            if cat_mode == "remove":
                state.setdefault("cat_actions", {}).setdefault(cat.id, set()).add("remove")
                state["step"] = 1
                state["cat_mode"] = None
                await message.channel.send(f"'{display}' 제거됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
                return
            state["pending_cat_id"] = cat.id
            state["pending_cat_name"] = display
            state["step"] = 6
            await message.channel.send(f"'{display}' 선택됨.\n\n작업 번호 입력:\n" + CAT_ACTION_MENU_TEXT)
            return

        matches = save_file.cats.get_cats_name(save_file, text)
        if not matches:
            await message.channel.send(f"'{text}' 검색 결과가 없어요.")
            return
        if len(matches) > 1:
            lines = [f"'{text}' 검색 결과 ({len(matches)}건)\n"]
            for cat in matches[:25]:
                lines.append(f"`{cat.id:>4}` │ {get_cat_display_name(save_file, cat)}")
            await message.channel.send("\n".join(lines))
            return

        cat = matches[0]
        display = get_cat_display_name(save_file, cat)
        if cat_mode == "remove":
            state.setdefault("cat_actions", {}).setdefault(cat.id, set()).add("remove")
            state["step"] = 1
            state["cat_mode"] = None
            await message.channel.send(f"'{display}' 제거됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
            return
        state["pending_cat_id"] = cat.id
        state["pending_cat_name"] = display
        state["step"] = 6
        await message.channel.send(f"'{display}' 선택됨.\n\n작업 번호 입력:\n" + CAT_ACTION_MENU_TEXT)
        return

    if state["step"] == 6:
        if message.content.strip() in ("0", "취소", "뒤로"):
            state["step"] = 4
            state.pop("pending_cat_id", None)
            state.pop("pending_cat_name", None)
            await message.channel.send("캐릭터 선택 취소됨.")
            return
        raw_parts = [p.strip() for p in message.content.split(",") if p.strip()]
        actions = {CAT_ACTION_MENU_KEYS[p] for p in raw_parts if p in CAT_ACTION_MENU_KEYS}
        if not actions:
            await message.channel.send("1~7 사이 번호를 입력해주세요.")
            return
        cat_id = state["pending_cat_id"]
        cat_name = state.get("pending_cat_name", str(cat_id))
        state.setdefault("cat_actions", {}).setdefault(cat_id, set()).update(actions)
        state["step"] = 1
        state["cat_mode"] = None
        await message.channel.send(f"'{cat_name}' 작업 적용됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
        return

    if state["step"] == 7:
        text = message.content.strip()
        if text in ("0", "취소", "뒤로"):
            state["step"] = 1
            await message.channel.send("항목 선택.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
            return
        actions = set()
        raw_parts = [p.strip() for p in text.split(",") if p.strip()]
        if any(p.lower() == "all" for p in raw_parts):
            actions.update(STORY_ACTION_MENU_KEYS.values())
        else:
            actions.update(STORY_ACTION_MENU_KEYS[p] for p in raw_parts if p in STORY_ACTION_MENU_KEYS)
        if not actions:
            await message.channel.send("1~6 사이 번호를 입력해주세요.")
            return
        state.setdefault("story_actions", set()).update(actions)
        state["step"] = 1
        await message.channel.send("스토리 작업 적용됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
        return

    if state["step"] == 8:
        text = message.content.strip()
        if text in ("0", "취소", "뒤로"):
            state["step"] = 1
            await message.channel.send("항목 선택.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
            return
        actions = set()
        raw_parts = [p.strip() for p in text.split(",") if p.strip()]
        if any(p.lower() == "all" for p in raw_parts):
            actions.update(MISC_ACTION_MENU_KEYS.values())
        else:
            actions.update(MISC_ACTION_MENU_KEYS[p] for p in raw_parts if p in MISC_ACTION_MENU_KEYS)
        if not actions:
            await message.channel.send("1~6 사이 번호를 입력해주세요.")
            return
        state.setdefault("misc_actions", set()).update(actions)
        state["step"] = 1
        await message.channel.send("콘텐츠 작업 적용됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
        return

    if state["step"] == 9:
        text = message.content.strip()
        if text in ("0", "취소", "뒤로"):
            state["step"] = 1
            await message.channel.send("항목 선택.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
            return
        actions = set()
        raw_parts = [p.strip() for p in text.split(",") if p.strip()]
        if any(p.lower() == "all" for p in raw_parts):
            actions.update(STAGE_ACTION_MENU_KEYS.values())
        else:
            actions.update(STAGE_ACTION_MENU_KEYS[p] for p in raw_parts if p in STAGE_ACTION_MENU_KEYS)
        if not actions:
            await message.channel.send("1~18 사이 번호를 입력해주세요.")
            return
        state.setdefault("stage_actions", set()).update(actions)
        state["step"] = 1
        await message.channel.send("스테이지 작업 적용됨.\n\n" + MAIN_MENU_TEXT, view=ConfirmView())
        return


class CloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_button")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if channel.name.startswith("close-ticket-"):
            await interaction.response.send_message("이미 닫힌 티켓이에요.", ephemeral=True)
            return
        await interaction.response.send_message("티켓을 닫는 중이에요...", ephemeral=True)
        await close_ticket_channel(channel, "티켓 수동 종료")


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(label="🎫티켓 생성", style=discord.ButtonStyle.green, custom_id="ticket_create_button")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        if not is_bot_admin(user):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        if user.id in open_tickets:
            channel = guild.get_channel(open_tickets[user.id])
            if channel:
                await interaction.response.send_message(f"이미 티켓이 있습니다.\n{channel.mention}", ephemeral=True)
                return
        category = discord.utils.get(guild.categories, name="티켓") or await guild.create_category("티켓")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        channel = await guild.create_text_channel(name=f"ticket-{user.name}", category=category, overwrites=overwrites)
        open_tickets[user.id] = channel.id
        ticket_owners[channel.id] = user.id
        await interaction.response.send_message(f"{channel.mention} 생성되었습니다.", ephemeral=True)
        welcome_embed = discord.Embed(description=f"안녕하세요 {user.mention}님!\n스태프가 곧 답변 드리겠습니다.", color=0x2ECC71)
        await channel.send(embed=welcome_embed, view=CloseButton())
        await asyncio.sleep(1)
        await channel.send(f"{user.mention}님 안녕하세요!\n어떤 일 때문에 티켓을 여셨나요?\n\n1. 이벤트\n2. 밴 해제")


admin_group = discord.app_commands.Group(name="관리자", description="냥코 봇 관리자 관리")

@admin_group.command(name="추가", description="사용자를 냥코 봇 관리자로 추가합니다.")
@discord.app_commands.describe(member="관리자로 추가할 디스코드 사용자")
async def add_admin(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id != BOT_OWNER_USER_ID:
        await interaction.response.send_message("봇 소유자만 사용할 수 있습니다.", ephemeral=True)
        return
    if member.bot or member.id in ADDED_ADMIN_USER_IDS:
        await interaction.response.send_message("추가할 수 없는 대상이거나 이미 관리자입니다.", ephemeral=True)
        return
    ADDED_ADMIN_USER_IDS.add(member.id)
    save_added_admin_ids()
    await interaction.response.send_message(f"{member.mention}님을 관리자로 추가했습니다.", ephemeral=True)

@admin_group.command(name="제거", description="사용자를 냥코 봇 관리자에서 제거합니다.")
@discord.app_commands.describe(member="관리자에서 제거할 디스코드 사용자")
async def remove_admin(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.id != BOT_OWNER_USER_ID:
        await interaction.response.send_message("봇 소유자만 사용할 수 있습니다.", ephemeral=True)
        return
    if member.id not in ADDED_ADMIN_USER_IDS:
        await interaction.response.send_message("추가된 관리자가 아닙니다.", ephemeral=True)
        return
    ADDED_ADMIN_USER_IDS.remove(member.id)
    save_added_admin_ids()
    await interaction.response.send_message(f"{member.mention}님을 관리자에서 제거했습니다.", ephemeral=True)


ticket_group = discord.app_commands.Group(name="티켓", description="냥코 티켓 관리")

@ticket_group.command(name="닫기", description="현재 티켓을 강제로 닫고 채널을 삭제합니다.")
async def force_close_ticket(interaction: discord.Interaction):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("티켓 채널에서만 사용할 수 있습니다.", ephemeral=True)
        return
    owner_id = ticket_owners.get(channel.id)
    if not (is_bot_admin(interaction.user) or interaction.user.id == owner_id):
        await interaction.response.send_message("권한이 없습니다.", ephemeral=True)
        return
    await interaction.response.send_message("티켓을 닫는 중...", ephemeral=True)
    await close_ticket_channel(channel, "강제 종료")


bot.tree.add_command(admin_group)
bot.tree.add_command(ticket_group)

@bot.tree.command(name="티켓패널", description="패널 표시")
async def ticketpanel_slash(interaction: discord.Interaction):
    if not is_bot_admin(interaction.user):
        await interaction.response.send_message("관리자만 가능합니다.", ephemeral=True)
        return
    embed = discord.Embed(title="냥코 티켓", description="버튼을 눌러 티켓 생성", color=0x2ECC71)
    await interaction.response.send_message(embed=embed, view=TicketView())

@bot.command(name="티켓패널")
@commands.check(lambda ctx: isinstance(ctx.author, discord.Member) and is_bot_admin(ctx.author))
async def ticketpanel(ctx: commands.Context):
    embed = discord.Embed(title="냥코 티켓", description="버튼을 눌러 티켓 생성", color=0x2ECC71)
    await ctx.send(embed=embed, view=TicketView())

