"""배치 스토리 생성기 — 다양성 매트릭스의 슬롯 하나를 스토리 JSON 하나로 만든다.

    cd apps/api && uv run python scripts/generate_seed_stories.py --dry-run
    cd apps/api && uv run python scripts/generate_seed_stories.py --genre romance
    cd apps/api && uv run python scripts/generate_seed_stories.py --genre horror --slot 2 --force

콘셉트(제목·한줄·타겟·좌표·스탯 축·시작 상황)는 `seed_content/data/diversity_matrix.json`
에서 이미 확정된 것이고 **생성기는 본문만 채운다** — 그래야 같은 장르 3개의 겹침을 생성
후가 아니라 생성 전에 막을 수 있다(PRD §6). 그래서 LLM 출력 스키마에는 아예 제목·한줄·
타겟이 없고, 스탯은 이름을 그대로 되풀이하게 한 뒤 검증에서 대조한다.

출력은 자유 텍스트 파싱이 아니라 `LLMClient.generate_structured()` 의 강제 스키마
(`GeneratedStory`)다. 받은 결과를 시드 JSON 모양으로 조립한 뒤, **파일로 쓰기 전에**
`seed_content.loader.parse_story` + `upsert._validate_payload` 로 실제 시드가 거는 관문을
그대로 통과시킨다. 실패하면 무엇이 틀렸는지를 프롬프트에 되먹여 재생성한다(최대 2회).
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from api.chat.ending_rules import evaluate_rule_list
from api.chat.router import _preview_ending_rule_list_item
from api.content.schemas import (
    EndingDraftItem,
    EndingRuleGroupDraftItem,
    StatDefDraftItem,
    StoryDraftPayload,
)
from api.core.config import settings
from api.db.models.story import StoryPromptTemplate
from api.llm.client import LLMClient, LLMClientError
from api.llm.dependencies import get_llm_client
from seed_content.loader import STORIES_DIR, SeedContentError, parse_story
from seed_content.matrix import MatrixSlot, load_matrix
from seed_content.upsert import _validate_payload

# 검증에 걸리면 무엇이 틀렸는지 되먹여 다시 부른다 — 첫 호출 + 재시도 2회.
MAX_ATTEMPTS = 3

# 구조 요건. 발행 검증(`turnCountGate >= 10` 등)과 겹치지 않는 것만 여기서 본다.
MIN_ENDINGS_PER_SETUP = 2
MIN_KEYWORD_NOTES = 4
MIN_SHORTCUTS = 2

# 스탯 아이콘/색은 자유 문자열이 아니라 FE 의 고정 목록에서만 골라야 화면에 제대로 뜬다
# (`apps/web/src/shared/ui/color-icon-picker/icons.ts`, `packages/ui/src/lib/color-palette.ts`).
# BE 스키마는 `str` 이라 아무 값이나 통과하므로 시드가 스스로 지킨다.
StatIcon = Literal[
    "Heart", "Zap", "Brain", "Shield", "Swords", "Star", "Smile", "Flame", "Droplet", "Moon", "Coins", "Sparkles"
]
StatColor = Literal["rose", "orange", "amber", "lime", "emerald", "teal", "sky", "indigo", "violet", "fuchsia"]
COLOR_VALUES: dict[StatColor, str] = {
    "rose": "oklch(0.62 0.19 350)",
    "orange": "oklch(0.68 0.17 45)",
    "amber": "oklch(0.78 0.17 80)",
    "lime": "oklch(0.75 0.19 130)",
    "emerald": "oklch(0.68 0.15 160)",
    "teal": "oklch(0.68 0.13 190)",
    "sky": "oklch(0.68 0.14 230)",
    "indigo": "oklch(0.55 0.18 270)",
    "violet": "oklch(0.6 0.19 300)",
    "fuchsia": "oklch(0.62 0.22 320)",
}

# 플레이 동사가 프롬프트 템플릿을 정한다 — 매트릭스가 정하지 않는 값이라 여기서 못 박는다.
PROMPT_TEMPLATE_BY_VERB: dict[str, StoryPromptTemplate] = {
    "공략": StoryPromptTemplate.EMOTIONAL,
    "추리": StoryPromptTemplate.BASIC,
    "생존": StoryPromptTemplate.SIMULATION,
}

# PRD §6 수위 규칙. 프롬프트에 그대로 들어간다.
CONTENT_RATING_RULES = (
    "[수위 규칙 — 전연령 서비스에 발행된다]\n"
    "- 허용: 집착, 감금 암시, 배신, 죽음, 신체 훼손, 정신적 붕괴 — 전부 서사 장치로서.\n"
    "- 금지: 선정성(노출 묘사, 성적 접촉과 그 암시), 혐오 표현, 자해 방법 묘사, 미성년 대상 연애 묘사.\n"
    "- 관계의 긴장은 최대로 밀되 위 금지선은 넘지 않는다."
)


class GeneratedStatDef(BaseModel):
    """스탯 하나. `name` 은 주어진 스탯 축 이름을 그대로 되풀이해야 한다(검증에서 대조)."""

    name: str
    icon: StatIcon
    color: StatColor
    min_value: int
    max_value: int
    initial_value: int
    unit: str
    description: str


class GeneratedEndingRule(BaseModel):
    """엔딩 규칙 하나. `stat` 은 같은 시작 상황 스탯의 **이름**이다(UUID 를 쓰지 않는다)."""

    stat: str
    operator: Literal["gte", "lte", "eq", "gt", "lt"]
    threshold: float


class GeneratedEnding(BaseModel):
    name: str
    turn_count_gate: int
    judgment_prompt: str
    epilogue: str
    hint: str
    stat_rule_logic: Literal["and", "or"]
    stat_rules: list[GeneratedEndingRule]


class GeneratedStartingSetup(BaseModel):
    name: str
    prologue: str
    opening_message: str
    playguide: str
    suggested_replies: list[str]
    stat_defs: list[GeneratedStatDef]
    endings: list[GeneratedEnding]


class GeneratedKeywordNote(BaseModel):
    info_text: str
    trigger_keywords: list[str]


class GeneratedShortcut(BaseModel):
    name: str
    description: str
    prompt: str


class GeneratedStory(BaseModel):
    """`generate_structured()` 강제 스키마 — 제목/한줄/타겟/장르는 매트릭스가 정하므로 없다."""

    setting_text: str
    development_example: str
    description: str
    hashtags: list[str]
    starting_setups: list[GeneratedStartingSetup]
    keyword_notes: list[GeneratedKeywordNote]
    shortcuts: list[GeneratedShortcut]


def stat_display_name(matrix_stat: str) -> str:
    """`남은 방송 회차(30→0)` 처럼 매트릭스가 달아둔 설계 주석을 뗀 표시 이름."""
    return matrix_stat.split("(")[0].strip()


def build_prompt(slot: MatrixSlot, previous: Sequence[str], errors: Sequence[str] = ()) -> str:
    """PRD §6 의 5단 구조 — 역할·제약 / 좌표와 콘셉트 / 누적 컨텍스트 / 구조 요건 / 출력 스키마."""
    sections = [
        "너는 한국어 인터랙티브 스토리를 쓰는 작가다. 아래 콘셉트는 이미 확정된 것이고, "
        "너는 콘셉트를 새로 만들지 않고 본문만 채운다.",
        _concept_section(slot),
        _previous_section(previous),
        CONTENT_RATING_RULES,
        _structure_section(slot),
    ]
    if errors:
        sections.append(
            "[직전 생성물이 검증에서 걸렸다 — 아래를 반드시 고쳐서 다시 써라]\n"
            + "\n".join(f"- {error}" for error in errors)
        )
    return "\n\n".join(section for section in sections if section)


def _concept_section(slot: MatrixSlot) -> str:
    axes = slot.axes
    setups = "\n".join(
        f"  {index + 1}. {setup}" for index, setup in enumerate(slot.starting_setups)
    )
    return (
        "[확정 콘셉트 — 한 글자도 바꾸지 마라]\n"
        f"- 제목: {slot.title}\n"
        f"- 한 줄 소개: {slot.one_liner}\n"
        f"- 장르: {slot.genre}\n"
        f"- 대상 독자: {slot.target}\n"
        f"- 세계관 요지: {slot.setting}\n"
        f"- 좌표: 정서 {axes.tone} / 관계 {axes.relation} / 플레이 {axes.verb} / "
        f"세계 {axes.space} / 엔딩 압력 {axes.ending_pressure}\n"
        f"- 스탯 축 {len(slot.stats)}개(괄호는 설계 주석이다 — 이름은 괄호 앞부분 그대로 쓴다): "
        f"{' · '.join(slot.stats)}\n"
        f"- 시작 상황 {len(slot.starting_setups)}개(이 상황 그대로, 이 순서로):\n{setups}\n"
        f"- 쓰면 안 되는 소재: {', '.join(slot.forbidden)}"
    )


def _previous_section(previous: Sequence[str]) -> str:
    if not previous:
        return ""
    return (
        "[같은 장르에서 이미 만든 스토리 — 소재·말투·문장 리듬·엔딩 판정 기준·키워드북 소재가 "
        "이것들과 겹치면 안 된다]\n" + "\n\n".join(previous)
    )


def _structure_section(slot: MatrixSlot) -> str:
    stat_names = ", ".join(stat_display_name(stat) for stat in slot.stats)
    return (
        "[구조 요건]\n"
        "- settingText: 대화를 진행할 서술자에게 주는 지시문. 무대·등장인물·진행 방식·금지사항을 "
        "포함하고, '응답 앞에 화자 이름이나 라벨을 붙이지 않는다'는 지시를 반드시 넣는다. 800~1500자.\n"
        "- developmentExample: 사용자와 서술자가 두 번 주고받는 짧은 예시 대화.\n"
        "- description: 상세 페이지에 뜨는 소개문 3~5문장. 제목과 한 줄 소개를 그대로 반복하지 않는다.\n"
        "- hashtags: 4~6개, '#' 없이 단어만.\n"
        f"- startingSetups: 정확히 {len(slot.starting_setups)}개. 각각 name(짧은 제목), "
        "prologue(2~4문장, 사용자를 '당신'으로 부른다), openingMessage(상대의 첫 발화), "
        "playguide(무엇을 노려야 하는지 1~2문장), suggestedReplies 3개. 시작 상황이 여러 개면 "
        "초기 스탯 값과 엔딩 구성이 서로 달라야 한다 — 한쪽을 복사해 오지 않는다.\n"
        f"- statDefs: 시작 상황마다 {len(slot.stats)}개이고 이름은 정확히 [{stat_names}] 여야 한다. "
        "description 에는 **언제 오르고 언제 내리는지**를 반드시 적는다(판단 LLM 은 이 설명만 본다). "
        "시간·자원 스탯은 '한 대목마다 반드시 1 줄고 절대 늘지 않는다'처럼 감소 방향을 못 박는다. "
        "unit 은 필요 없으면 빈 문자열로 둔다.\n"
        f"- endings: 시작 상황마다 {MIN_ENDINGS_PER_SETUP}~3개. turnCountGate 는 10 이상. "
        "judgmentPrompt 는 대화 로그만 보고 예/아니오를 가릴 수 있는 구체적 문장이어야 한다"
        "('감동적인 순간' 같은 모호한 기준 금지). epilogue 3~5문장, hint 한 줄. "
        "**도달 조건이 좁은 엔딩을 앞에, 넓은 폴백을 뒤에 둔다**(앞의 것이 먼저 판정된다).\n"
        "- statRules: 엔딩마다 1~2개. stat 에는 같은 시작 상황 스탯의 이름을 쓴다. threshold 는 그 스탯의 "
        "[minValue, maxValue] 안이어야 하고, **초기값 그대로는 절대 만족되면 안 된다** "
        "(초기값에서 이미 참이면 스탯이 장식이 된다).\n"
        f"- keywordNotes: {MIN_KEYWORD_NOTES}~6개. triggerKeywords 는 사용자가 실제로 칠 법한 "
        "한국어 단어 3~6개.\n"
        f"- shortcuts: {MIN_SHORTCUTS}개. 사용자가 한 번에 보낼 수 있는 행동 버튼이다.\n"
        "\n모든 문장은 한국어로 쓴다."
    )


def assemble_story(slot: MatrixSlot, generated: GeneratedStory) -> dict[str, Any]:
    """LLM 결과 + 매트릭스 확정값을 시드 JSON 모양(camelCase, id 없음)으로 합친다."""
    return {
        "name": slot.title,
        "oneLiner": slot.one_liner,
        "thumbnailAssetId": None,  # 시드 실행 시점에 `ensure_asset` 이 채운다
        "promptTemplate": PROMPT_TEMPLATE_BY_VERB[slot.axes.verb].value,
        "settingText": generated.setting_text,
        "developmentExample": generated.development_example,
        "customPrompt": None,
        "startingSetups": [_setup_json(setup) for setup in generated.starting_setups],
        "keywordNotes": [
            {
                "infoText": note.info_text,
                "triggerKeywords": list(note.trigger_keywords),
                "startingSetupId": None,  # 파생 id 를 손으로 못 쓴다 — 스토리 전체 적용
            }
            for note in generated.keyword_notes
        ],
        "shortcuts": [
            {"name": shortcut.name, "description": shortcut.description, "prompt": shortcut.prompt}
            for shortcut in generated.shortcuts
        ],
        "description": generated.description,
        "genreId": str(slot.genre_id),
        "target": slot.target,
        "hashtags": list(generated.hashtags),
        "visibility": "public",
    }


def _setup_json(setup: GeneratedStartingSetup) -> dict[str, Any]:
    return {
        "name": setup.name,
        "prologue": setup.prologue,
        "openingMessage": setup.opening_message,
        "playguide": setup.playguide,
        "suggestedReplies": list(setup.suggested_replies),
        "statDefs": [
            {
                "name": stat.name,
                "icon": stat.icon,
                "color": COLOR_VALUES[stat.color],
                "minValue": stat.min_value,
                "maxValue": stat.max_value,
                "initialValue": stat.initial_value,
                "unit": stat.unit or None,
                "description": stat.description,
            }
            for stat in setup.stat_defs
        ],
        "endings": [_ending_json(ending) for ending in setup.endings],
    }


def _ending_json(ending: GeneratedEnding) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for index, rule in enumerate(ending.stat_rules):
        item: dict[str, Any] = {
            "kind": "rule",
            "stat": rule.stat,
            "operator": rule.operator,
            "threshold": rule.threshold,
        }
        if index < len(ending.stat_rules) - 1:
            item["nextOp"] = ending.stat_rule_logic
        rules.append(item)
    return {
        "name": ending.name,
        "turnCountGate": ending.turn_count_gate,
        "judgmentPrompt": ending.judgment_prompt,
        "epilogue": ending.epilogue or None,
        "hint": ending.hint or None,
        "statRules": rules,
    }


def validate_story(slot: MatrixSlot, raw: dict[str, Any]) -> list[str]:
    """파일로 쓰기 전에 시드가 실제로 거는 관문을 그대로 통과시킨다 — 어긋난 이유 목록."""
    try:
        payload = parse_story(raw, slot.slug)
    except SeedContentError as exc:
        return [str(exc)]

    # 썸네일은 시드 실행 시점에 채워지므로 발행 검증용 자리표시자를 넣는다.
    missing = _validate_payload(payload.model_copy(update={"thumbnail_asset_id": uuid.uuid4()}))
    errors = [f"발행 검증에서 빈 필드/깨진 참조: {', '.join(missing)}"] if missing else []
    return errors + _structure_errors(slot, payload)


def _structure_errors(slot: MatrixSlot, payload: StoryDraftPayload) -> list[str]:
    errors: list[str] = []
    expected_stats = sorted(stat_display_name(stat) for stat in slot.stats)

    if len(payload.starting_setups) != len(slot.starting_setups):
        errors.append(
            f"시작 상황이 {len(payload.starting_setups)}개다 — {len(slot.starting_setups)}개여야 한다"
        )
    if len(payload.keyword_notes) < MIN_KEYWORD_NOTES:
        errors.append(f"keywordNotes 가 {len(payload.keyword_notes)}개다 — {MIN_KEYWORD_NOTES}개 이상")
    if len(payload.shortcuts) < MIN_SHORTCUTS:
        errors.append(f"shortcuts 가 {len(payload.shortcuts)}개다 — {MIN_SHORTCUTS}개 이상")

    for setup_index, setup in enumerate(payload.starting_setups):
        where = f"startingSetups[{setup_index}]"
        if sorted(stat.name for stat in setup.stat_defs) != expected_stats:
            errors.append(
                f"{where}: 스탯 이름이 {[stat.name for stat in setup.stat_defs]} 다 "
                f"— {expected_stats} 와 정확히 같아야 한다"
            )
        for stat in setup.stat_defs:
            if not stat.min_value <= stat.initial_value <= stat.max_value:
                errors.append(
                    f"{where}: 스탯 '{stat.name}' 의 초기값 {stat.initial_value} 이 "
                    f"[{stat.min_value}, {stat.max_value}] 밖이다"
                )
        if len(setup.endings) < MIN_ENDINGS_PER_SETUP:
            errors.append(
                f"{where}: 엔딩이 {len(setup.endings)}개다 — {MIN_ENDINGS_PER_SETUP}개 이상"
            )
        errors += _ending_rule_errors(where, setup.stat_defs, setup.endings)
    return errors


def _ending_rule_errors(
    where: str, stat_defs: Sequence[StatDefDraftItem], endings: Sequence[EndingDraftItem]
) -> list[str]:
    """임계값이 스탯 범위 안인지 + 초기값 그대로는 규칙이 만족되지 않는지."""
    errors: list[str] = []
    stats_by_id = {stat.id: stat for stat in stat_defs}
    initial_values = {str(stat.id): float(stat.initial_value) for stat in stat_defs}

    for ending_index, ending in enumerate(endings):
        label = f"{where}.endings[{ending_index}] '{ending.name}'"
        for item in ending.stat_rules:
            rules = item.rules if isinstance(item, EndingRuleGroupDraftItem) else [item]
            for rule in rules:
                stat = stats_by_id.get(rule.stat_id)
                if stat is None:
                    continue  # 이름 해석 단계에서 이미 걸린다
                if not stat.min_value <= rule.threshold <= stat.max_value:
                    errors.append(
                        f"{label}: '{stat.name}' 임계값 {rule.threshold} 이 "
                        f"[{stat.min_value}, {stat.max_value}] 밖이라 영영 도달할 수 없다"
                    )
        rule_items = [_preview_ending_rule_list_item(item) for item in ending.stat_rules]
        if evaluate_rule_list(rule_items, initial_values):
            errors.append(
                f"{label}: 스탯이 하나도 안 움직여도 규칙이 만족된다 — 임계값을 초기값에서 떨어뜨려라"
            )
    return errors


def summarize(slot: MatrixSlot, raw: dict[str, Any]) -> str:
    """다음 슬롯 프롬프트에 넣을 '이것과 겹치지 마라' 요약."""
    setting = str(raw.get("settingText") or "").replace("\n", " ")
    endings = [
        str(ending.get("name"))
        for setup in raw.get("startingSetups") or []
        for ending in setup.get("endings") or []
    ]
    keywords = [
        keyword
        for note in raw.get("keywordNotes") or []
        for keyword in (note.get("triggerKeywords") or [])
    ]
    return (
        f"- 「{raw.get('name')}」({slot.slug}) — {raw.get('oneLiner')}\n"
        f"  설정 요지: {setting[:200]}\n"
        f"  엔딩: {', '.join(endings)}\n"
        f"  키워드북 소재: {', '.join(map(str, keywords[:12]))}"
    )


def main() -> int:
    args = _parse_args()
    try:
        slots = load_matrix()
    except SeedContentError as exc:
        print(f"다양성 매트릭스를 읽지 못했다 — {exc}")
        return 1

    selected = _select(slots, args.genre, args.slot)
    if selected is None:
        return 1

    if args.dry_run:
        _print_dry_run(slots, selected)
        return 0

    if not settings.gemini_api_key:
        print(
            "GEMINI_API_KEY 가 비어 있어 스토리를 생성할 수 없다.\n"
            "  apps/api/.env 에 값을 넣고 다시 실행할 것. (--dry-run 은 키 없이도 프롬프트를 보여준다)"
        )
        return 1

    return asyncio.run(_generate_all(slots, selected, force=bool(args.force)))


def _select(slots: list[MatrixSlot], genre: str | None, slot_number: int | None) -> set[str] | None:
    """생성 대상 slug 집합. 필터가 아무것도 못 고르면 안내를 찍고 `None`."""
    chosen = [slot for slot in slots if not slot.hand_written]
    if genre is not None:
        chosen = [slot for slot in chosen if genre in (slot.genre, _genre_slug(slot))]
        if not chosen:
            available = sorted({_genre_slug(slot) for slot in slots})
            print(f"--genre {genre} 에 해당하는 장르가 없다 — {available} 중 하나여야 한다")
            return None
    if slot_number is not None:
        chosen = [slot for slot in chosen if slot.slot == slot_number]
        if not chosen:
            print(f"--slot {slot_number} 에 해당하는 슬롯이 없다")
            return None
    return {slot.slug for slot in chosen}


async def _generate_all(slots: list[MatrixSlot], selected: set[str], *, force: bool) -> int:
    client = get_llm_client()
    failed: list[str] = []

    for genre, group in _by_genre(slots):
        if not any(slot.slug in selected for slot in group):
            continue
        print(f"\n[{genre}]")
        previous: list[str] = []
        for slot in group:
            existing = _read_existing(slot.slug)
            if slot.slug not in selected or (existing is not None and not force):
                if existing is not None:
                    previous.append(summarize(slot, existing))
                    if slot.slug in selected:
                        print(f"  - {slot.slug}: 이미 있음 — 건너뜀 (--force 로 재생성)")
                continue

            print(f"  · {slot.slug}: 「{slot.title}」 생성 중…")
            raw = await _generate_slot(client, slot, previous)
            if raw is None:
                failed.append(slot.slug)
                continue
            path = _write_story(slot.slug, raw)
            print(f"  ✓ {slot.slug} → {path}")
            previous.append(summarize(slot, raw))

    if failed:
        print(f"\n실패 {len(failed)}건: {', '.join(failed)} — 프롬프트나 콘셉트를 보고 다시 돌릴 것")
        return 1
    print(f"\n완료 — {STORIES_DIR}")
    return 0


async def _generate_slot(
    client: LLMClient, slot: MatrixSlot, previous: Sequence[str]
) -> dict[str, Any] | None:
    errors: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            generated = await client.generate_structured(build_prompt(slot, previous, errors), GeneratedStory)
        except LLMClientError as exc:
            print(f"    ! {attempt}차 생성 호출 실패 — {exc}")
            continue
        raw = assemble_story(slot, generated)
        errors = validate_story(slot, raw)
        if not errors:
            return raw
        print(f"    ! {attempt}차 검증 실패 {len(errors)}건")
        for error in errors:
            print(f"        · {error}")
    return None


def _print_dry_run(slots: list[MatrixSlot], selected: set[str]) -> None:
    print(f"생성 대상 {len(selected)}개 (API 호출 없음)\n")
    for genre, group in _by_genre(slots):
        previous: list[str] = []
        for slot in group:
            existing = _read_existing(slot.slug)
            if slot.slug in selected:
                print(f"{'=' * 70}\n[{genre}] {slot.slug} — 「{slot.title}」")
                if existing is not None:
                    print("  (파일이 이미 있다 — 실제 실행은 --force 없이는 건너뛴다)")
                print(build_prompt(slot, previous))
                print()
            if existing is not None:
                # 실제 실행에서는 방금 생성한 슬롯의 요약도 여기 쌓인다.
                previous.append(summarize(slot, existing))


def _by_genre(slots: list[MatrixSlot]) -> list[tuple[str, list[MatrixSlot]]]:
    """장르별로 묶고 슬롯 번호 순으로 정렬한다 — 같은 장르는 앞 슬롯이 뒤 슬롯의 입력이다."""
    grouped: dict[str, list[MatrixSlot]] = {}
    for slot in slots:
        grouped.setdefault(slot.genre, []).append(slot)
    return [(genre, sorted(group, key=lambda s: s.slot)) for genre, group in grouped.items()]


def _genre_slug(slot: MatrixSlot) -> str:
    return slot.slug.split("-", 1)[0]


def _story_path(slug: str) -> Path:
    return STORIES_DIR / f"{slug}.json"


def _read_existing(slug: str) -> dict[str, Any] | None:
    path = _story_path(slug)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ! {slug}: 기존 파일을 읽지 못해 요약에서 뺀다 — {exc}")
        return None
    return raw if isinstance(raw, dict) else None


def _write_story(slug: str, raw: dict[str, Any]) -> Path:
    path = _story_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="다양성 매트릭스의 슬롯을 시드 스토리 JSON 으로 생성한다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--genre", metavar="SLUG", help="장르 하나만 생성한다 (예: romance / 로맨스)")
    parser.add_argument("--slot", type=int, help="슬롯 번호 하나만 생성한다 (1~3)")
    parser.add_argument("--force", action="store_true", help="이미 있는 JSON 도 다시 생성한다")
    parser.add_argument(
        "--dry-run", action="store_true", help="API 호출 없이 조립된 프롬프트만 출력한다"
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
