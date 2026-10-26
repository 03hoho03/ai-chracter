import hashlib
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from string import Formatter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.exceptions import RedisError
from sqlalchemy import Integer, cast, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.action_log import record_admin_action
from api.admin.dependencies import get_current_admin_id
from api.admin.prompt_semver import (
    SPEAKER_LABELS,
    SemverLevelError,
    SemverPlan,
    diff_sections,
    draft_fingerprint,
    format_semver,
    load_base,
    plan_semver,
    section_contents,
    section_semvers_of,
    semvers_of,
    write_semver,
)
from api.admin.schemas import (
    AdminPromptDraftChangesResponse,
    AdminPromptDraftResponse,
    AdminPromptDraftUpsertRequest,
    AdminPromptLabels,
    AdminPromptPlaceholderHint,
    AdminPromptPreviewItem,
    AdminPromptPreviewResponse,
    AdminPromptPublishRequest,
    AdminPromptRatingDrift,
    AdminPromptSectionChange,
    AdminPromptSectionItem,
    AdminPromptSectionRestoreRequest,
    AdminPromptSectionSemver,
    AdminPromptSetDetailResponse,
    AdminPromptSetListResponse,
    AdminPromptSetRestoreRequest,
    AdminPromptSetSummary,
)
from api.chat.prompt_builder import (
    PromptSetNotFoundError,
    ALLOWED_PLACEHOLDERS,
    MediaCellCandidate,
    PromptLane,
    PromptRenderError,
    PromptNames,
    as_prompt_lane,
    build_generation_prompt,
    build_memory_episode_prompt,
    build_memory_fact_prompt,
    build_memory_impression_prompt,
    build_memory_summary_prompt,
    build_scene_judgment_prompt,
    build_stat_rule_judgment_prompt,
    build_story_generation_prompt,
    format_user_persona,
    load_active_prompt_set,
    media_cell_image_lines,
    select_sections_for_render,
    situational_image_lines,
    system_instruction_for,
)
from api.chat.prompt_builder import build_ending_judgment_prompt as _build_ending_judgment_prompt
from api.chat.prompt_builder import build_image_judgment_prompt as _build_image_judgment_prompt
from api.chat.prompt_set_cache import invalidate_active_prompt_set
from api.chat.prompt_stages import stage_channels
from api.content.author_macros import expand_author_macros
from api.content.publish import (
    MediaBookFilterCell,
    build_character_publish_filter_prompt,
    build_story_publish_filter_prompt,
)
from api.core.sentry import capture_dependency_failure
from api.db.models.character import SituationalImage
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.prompt import PromptSection, PromptSet
from api.db.models.story import StatDef, StatRule, StoryPromptTemplate
from api.db.session import get_db_session
from api.llm.chat_models import PromptSetModelId, parse_prompt_set_model_id
from api.novel_public.screening import NovelScreenItem, build_novel_screen_prompt
from api.novelize.inputs import load_novel_label_set
from api.novelize.prompts import (
    RATING_CHANNEL,
    NovelizePrompt,
    build_novelize_boundary_prompt,
    build_novelize_chapter_prompt,
    build_novelize_episode_outline_prompt,
    build_novelize_outline_prompt,
    build_novelize_revise_blocks_prompt,
    build_novelize_revise_prompt,
    build_novelize_revise_recheck_prompt,
    render_rating,
)

router = APIRouter(tags=["admin"])

logger = logging.getLogger(__name__)

# 채팅 레인(story·character Gemini 체인)에 얼려 둔 옛 소설화 세 채널 — 두 레인에 같은 행이 `scope="both"` 로 있다.
# 소설 문안은 `novel` 레인으로 옮겼지만 이 행은 지우지 않는다: 옛 이미지로 되돌리면 옛 코드가 소설 문안을 여기서 읽기
# 때문이다. 그래서 채팅 레인 게시는 이 행을 계속 요구하되 어드민이 바꾸지 못하게 서버가 직전 게시본의 값을 복사한다
# (`_active_frozen_novel_sections`).
_FROZEN_NOVELIZE_ROWS: dict[str, frozenset[tuple[str, str, str]]] = {
    "novelize_boundary": frozenset(
        {("both", slot, "") for slot in ("instruction", "user_name", "max_turns", "turn_context")}
    ),
    "novelize_chapter": frozenset(
        {
            ("both", slot, "")
            for slot in ("instruction", "work_setting", "user_name", "setting_notes", "previous_excerpt", "turn_context")
        }
    ),
    "novelize_revise": frozenset(
        {
            ("both", slot, "")
            for slot in ("instruction", "work_setting", "setting_notes", "paragraphs", "target_range", "user_request")
        }
    ),
}
_NOVELIZE_CHANNELS: frozenset[str] = frozenset(_FROZEN_NOVELIZE_ROWS)

# `novel` 레인(소설 문안). 경계 제안·문단 수정은 얼린 행과 같은 슬롯이고, 화 생성은 한 번에 여러 화를 쓰게 되며 인물
# 메모·지난 화 요약·화 수 지시 슬롯이 늘었고, 구성 흐름 원고의 장면 계획·연속성 참고 슬롯이 더해졌다. 구성 흐름의 전체
# 구성안·장면 구성안 두 채널은 구성안 문안 리비전이 세 체인에 심었다. 여러 문단 수정과 그 묶음 재검사 두 채널도 있다 — 얼린
# 행 집합과 다른 새 집합이라 채팅 레인 게시 검증은 그대로다. 소설 채널은 스토리·캐릭터 원작이 같은 행을 `scope="both"` 로 함께
# 쓴다. 등급 규칙 채널 `novelize_rating` 만 원작 종류마다 scope `story`·`character` 한 행씩이다 — 소설 호출이 붙이는 등급 규칙을
# 채팅 레인에서 빌리지 않고 소설 레인에서 따로 손질하게 하되, 원작 종류마다 다른 채팅 등급 규칙에서 옮겨 온 값이라 두 행이다.
_NOVEL_LANE_ROWS: dict[str, frozenset[tuple[str, str, str]]] = {
    "novelize_boundary": _FROZEN_NOVELIZE_ROWS["novelize_boundary"],
    "novelize_chapter": frozenset(
        {
            ("both", slot, "")
            for slot in (
                "instruction",
                "work_setting",
                "user_name",
                "setting_notes",
                "character_notes",
                "previous_summaries",
                "previous_excerpt",
                "episode_plan",
                "turn_context",
                "scene_plan",
                "continuity_context",
            )
        }
    ),
    "novelize_revise": _FROZEN_NOVELIZE_ROWS["novelize_revise"],
    "novelize_revise_blocks": frozenset(
        {
            ("both", slot, "")
            for slot in ("instruction", "work_setting", "setting_notes", "paragraphs", "target_blocks", "user_request")
        }
    ),
    "novelize_revise_recheck": frozenset(
        {("both", slot, "") for slot in ("instruction", "context", "edited_paragraphs", "pending_patches")}
    ),
    "novelize_outline": frozenset(
        {
            ("both", slot, "")
            for slot in (
                "instruction",
                "work_setting",
                "user_name",
                "setting_notes",
                "character_notes",
                "previous_summaries",
                "continuity_context",
                "outline_plan",
                "turn_context",
            )
        }
    ),
    "novelize_episode_outline": frozenset(
        {
            ("both", slot, "")
            for slot in (
                "instruction",
                "work_setting",
                "user_name",
                "setting_notes",
                "character_notes",
                "previous_summaries",
                "episode_outline",
                "continuity_context",
                "turn_context",
            )
        }
    ),
    "novelize_rating": frozenset({("story", "rule_rating", ""), ("character", "rule_rating", "")}),
}

# 코드가 레인별로 아는 (channel, scope, slot, variant)
# 정확한 집합. 마이그레이션 a69cbd40dec8이 심은 레인별 26/13/16행에 b72c33c70240이 story·
# character generation에 `user_persona`를 한 행씩 더한 27/14/16행, 여기에 c328445d4c2d가 채팅방
# 기억 행(generation 2 · story ending_judgment 1 · 새 channel `memory_summary` 3)을 더한 33/19/16행에,
# 2519dde454e0이 story 레인에 미디어 북 칸 판정 channel `image_judgment` 3행을 더한 36/19/16행, 여기에
# bd29dd69bc0f가 publish_filter 레인에 미디어 북 칸 줄 슬롯 `media_book` 1행을 더한 36/19/17행, 여기에
# 859b0fb86629가 publish_filter 레인의 작가 글 슬롯 13개를 빼고 이미지 목록 슬롯 `image_list` 1행을 더한
# 36/19/4행, 2417f5829bb1이 story generation 에 상황 노트 행 1개를 더한 37/19/4행, 여기에 사용자 이름 한 줄
# 리비전이 슬롯 `user_name`을 story 5행(generation·stat·ending·image 판정·요약)·character 3행(generation·image 판정·
# 요약) 더한 42/22/4행, 여기에 소설화 채널 리비전이 소설화 세 채널(장 경계 제안 4·장 생성 6·문단 수정 6)을 story·
# character 에 16행씩 더한 58/38/4행, 스탯 규칙 판정 채널 리비전 `d9768bc0cfee`가 story 에 4행을 더한 62/38/4행, 여기에
# 장면 기억 문안 리비전 `fc6f0e134782`가 두 레인에 회상 슬롯 `memory_recall` 1행과 추출 채널 `memory_episode` 4행을 더한
# 67/43/4행, 관계·사실 기억 문안 리비전 `5cab2abe4e7b`가 두 레인에 사실 슬롯 `memory_facts` 1행과 추출 채널 `memory_fact` 4행을
# 더한 72/48/4행, 요약 비밀 표기 리비전 `0aeadefcf159`가 두 레인 요약 채널에 `secret_marking` 1행을 더한 73/49/4행, 장면 헤더 판정
# 문안 리비전이 story 에 판정 채널 `scene_judgment` 3행을 더한 76/49/4행, 인상 생성 문안 리비전 `6558ab4d3dbc` 가 두 레인에 채널
# `memory_impression` 3행을 더한 79/52/4행과 정확히 같다. 소설 프롬프트 레인 리비전이 만든 `novel` 레인은 경계 제안 4·화 생성
# 9·문단 수정 6 의 19행이었고(story·character 의 소설화 16행은 그대로 얼려 둔다), 구성안 문안 리비전 `b389c2317149` 가 화 생성에
# 2행·전체 구성안 9행·장면 구성안 9행을 더해 39행이고, 여러 문단 수정 문안 리비전 `174f78b92e5c` 가 Gemini 체인에만 여러 문단
# 수정 6행·묶음 재검사 4행을 더해 Gemini 체인은 49행이고, Claude 체인 채널 리비전 `fe3df6f8e4d5` 가 Claude 두 체인에 같은 네 채널
# 20행을 더해 세 체인이 같은 49행이 되었고, 등급 규칙 리비전 `e4df46a80bfa` 가 세 체인에 `novelize_rating` 2행을 더해 51행이다.
# `tests/test_prompt_seed.py`의 `_EXPECTED_SLOTS_BY_LANE`이 "시드가 이 표와 일치하는가"를 보는
# 반면, 이 상수는 "임의의 초안이 이 표와 일치하는가"(게시 검증)를 본다 — 검증 대상이
# 달라 두 파일에 따로 둔다(시드 하나는 상수 데이터, 이건 임의 입력을 거부하는 게이트).
#
# R-1은 이 표에서 `variant`를 뗀 (channel, scope, slot) 수준으로만 본다 — 뗀 이유는
# R-2와 겹치지 않기 위해서다. `variant`까지 그대로 정확 일치를 요구하면
# `template_instruction`의 variant 하나를 지웠을 때 "슬롯 집합 불일치"(R-1)로도 이미
# 걸려서 R-2("R-2가 유일한 방어다")가 영원히 발동할 기회가 없다 — 두 규칙이 같은 입력을
# 두고 항상 같은 순서로 겹치면 뒤엣것은 죽은 코드다. 그래서 R-1은 "그 슬롯이 (scope
# 기준으로) 존재는 하는가"만 보고, "그 슬롯의 variant가 전부 있는가"는 R-2 전담이다.
_EXPECTED_ROWS_BY_LANE: dict[PromptLane, dict[str, frozenset[tuple[str, str, str]]]] = {
    "story": {
        "system": frozenset(
            {
                ("story", "self_definition", ""),
                ("both", "rule_response_format", ""),
                ("both", "rule_user_agency", ""),
                ("both", "rule_open_turn", ""),
                ("both", "rule_rating", ""),
                ("story", "template_instruction", "basic"),
                ("story", "template_instruction", "emotional"),
                ("story", "template_instruction", "simulation"),
                ("story", "template_instruction", "custom"),
                ("both", "priority_tail", ""),
            }
        ),
        "generation": frozenset(
            {
                ("story", "base_content", ""),
                ("story", "base_content", "custom"),
                ("story", "rules", ""),
                ("story", "user_goal", ""),
                ("story", "development_examples", ""),
                ("story", "prologue", ""),
                # 마이그레이션 `b72c33c70240`이 DB에 넣는 행과 같이 간다.
                # 코드만 있으면 R-1 "누락", DB만 있으면 "잉여"로 게시가 전부 막힌다.
                ("both", "user_persona", ""),
                # 사용자 이름 한 줄 마이그레이션이 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유). 이 채널 아래
                # 판정·요약 채널의 `user_name` 행도 같다.
                ("both", "user_name", ""),
                # 마이그레이션 `c328445d4c2d`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
                ("both", "memory_note", ""),
                ("both", "memory_summary", ""),
                ("both", "history", ""),
                # 마이그레이션 `5cab2abe4e7b`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
                ("both", "memory_facts", ""),
                # 마이그레이션 `fc6f0e134782`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
                ("both", "memory_recall", ""),
                ("story", "keyword_notes", ""),
                # 마이그레이션 `2417f5829bb1`이 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
                ("story", "situation_notes", ""),
                ("story", "shortcut_prompt", ""),
                ("both", "final_frame", ""),
            }
        ),
        # 옛 절대값 판정 채널. 더 이상 렌더하지 않지만 운영 프롬프트 세트에 행이 남아 있어, 여기서 빼면 그 행이 "잉여"로
        # 잡혀 story 레인 게시가 막힌다 — 게시 검증용으로만 둔다.
        "stat_judgment": frozenset(
            {
                ("story", "stat_defs_intro", ""),
                ("story", "user_name", ""),
                ("story", "turn_context", ""),
                ("story", "judgment_instruction", ""),
            }
        ),
        # 마이그레이션 `d9768bc0cfee`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
        "stat_rule_judgment": frozenset(
            {
                ("story", "stat_defs_intro", ""),
                ("story", "user_name", ""),
                ("story", "turn_context", ""),
                ("story", "judgment_instruction", ""),
            }
        ),
        # 장면 헤더 판정 문안 리비전이 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
        "scene_judgment": frozenset(
            {
                ("story", "instruction", ""),
                ("story", "previous_scene", ""),
                ("story", "turn_context", ""),
            }
        ),
        "ending_judgment": frozenset(
            {
                ("story", "user_name", ""),
                ("story", "memory_summary", ""),
                ("story", "history_header", ""),
                ("story", "turn_context", ""),
                ("story", "criteria", ""),
            }
        ),
        "memory_summary": frozenset(
            {
                ("both", "instruction", ""),
                ("both", "secret_marking", ""),
                ("both", "user_name", ""),
                ("both", "previous_summary", ""),
                ("both", "turn_context", ""),
            }
        ),
        # 마이그레이션 `fc6f0e134782`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
        "memory_episode": frozenset(
            {
                ("both", "instruction", ""),
                ("both", "user_name", ""),
                ("both", "previous_titles", ""),
                ("both", "turn_context", ""),
            }
        ),
        # 마이그레이션 `5cab2abe4e7b`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
        "memory_fact": frozenset(
            {
                ("both", "instruction", ""),
                ("both", "user_name", ""),
                ("both", "existing_facts", ""),
                ("both", "turn_context", ""),
            }
        ),
        # 인상 생성 문안 리비전 `6558ab4d3dbc`가 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
        "memory_impression": frozenset(
            {
                ("both", "instruction", ""),
                ("both", "episodes", ""),
                ("both", "facts", ""),
            }
        ),
        # 마이그레이션 `2519dde454e0`이 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
        "image_judgment": frozenset(
            {
                ("story", "image_list_intro", ""),
                ("story", "user_name", ""),
                ("story", "turn_context", ""),
                ("story", "judgment_instruction", ""),
            }
        ),
        # 소설화 채널 리비전이 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유). 두 레인이 같고, 지금은 얼린 행이다.
        **_FROZEN_NOVELIZE_ROWS,
    },
    "character": {
        "system": frozenset(
            {
                ("character", "self_definition", ""),
                ("both", "rule_response_format", ""),
                ("both", "rule_user_agency", ""),
                ("both", "rule_open_turn", ""),
                ("both", "rule_rating", ""),
                ("both", "priority_tail", ""),
            }
        ),
        "generation": frozenset(
            {
                ("character", "character_prompt", ""),
                ("character", "example_dialogues", ""),
                ("both", "user_persona", ""),  # 위 story와 같다
                ("both", "user_name", ""),
                ("both", "memory_note", ""),
                ("both", "memory_summary", ""),
                ("both", "history", ""),
                ("both", "memory_facts", ""),
                ("both", "memory_recall", ""),
                ("both", "final_frame", ""),
            }
        ),
        "image_judgment": frozenset(
            {
                ("character", "image_list_intro", ""),
                ("character", "user_name", ""),
                ("character", "turn_context", ""),
                ("character", "judgment_instruction", ""),
            }
        ),
        "memory_summary": frozenset(  # 위 story와 같다
            {
                ("both", "instruction", ""),
                ("both", "secret_marking", ""),
                ("both", "user_name", ""),
                ("both", "previous_summary", ""),
                ("both", "turn_context", ""),
            }
        ),
        "memory_episode": frozenset(  # 위 story와 같다
            {
                ("both", "instruction", ""),
                ("both", "user_name", ""),
                ("both", "previous_titles", ""),
                ("both", "turn_context", ""),
            }
        ),
        "memory_fact": frozenset(  # 위 story와 같다
            {
                ("both", "instruction", ""),
                ("both", "user_name", ""),
                ("both", "existing_facts", ""),
                ("both", "turn_context", ""),
            }
        ),
        "memory_impression": frozenset(  # 위 story와 같다
            {
                ("both", "instruction", ""),
                ("both", "episodes", ""),
                ("both", "facts", ""),
            }
        ),
        **_FROZEN_NOVELIZE_ROWS,  # 위 story와 같다
    },
    "publish_filter": {
        "publish_filter": frozenset(
            {
                ("character", "intro_instruction", ""),
                ("story", "intro_instruction", ""),
                ("both", "image_list", ""),
                ("both", "verdict_instruction", ""),
            }
        ),
    },
    "novel": _NOVEL_LANE_ROWS,
    # 노벨 텍스트 심사 레인 시드 리비전이 DB에 넣는 행과 같이 간다(위 user_persona와 같은 이유).
    "novel_screen": {
        "novel_screen": frozenset({("both", "instruction", ""), ("both", "screened_text", "")}),
    },
}

# R-1이 실제로 보는 것 — 위 표에서 `variant`를 뗀 (scope, slot) 집합. 새 목록을 손으로
# 또 적지 않고 `_EXPECTED_ROWS_BY_LANE`에서 뽑는다(두 벌이면 template_instruction/
# base_content의 variant 행 수가 바뀔 때 한쪽만 갱신되고 갈린다).
_EXPECTED_SLOTS_BY_LANE: dict[PromptLane, dict[str, frozenset[tuple[str, str]]]] = {
    lane: {
        channel: frozenset((scope, slot) for scope, slot, _variant in rows)
        for channel, rows in by_channel.items()
    }
    for lane, by_channel in _EXPECTED_ROWS_BY_LANE.items()
}

# 채팅 레인의 판정(스탯 규칙·장면 헤더·엔딩·그림)·기억 요약·장면 기억 추출·관계·사실 기억 추출·인상 생성 호출이 읽는 채널. 옛 `stat_judgment` 은 읽는 코드가 없어
# Gemini 체인에만 남아 있다. 판정·요약 문안 체인이 있는 레인은 story·character 뿐이다. 채팅 두 레인의 값은 단계 표에서 생성을
# 뺀 단계들의 채널로 도출한다 — 모델 배정 저장 검사도 같은 표로 체인의 채널을 보므로, 따로 적으면 한쪽만 고쳐진다.
# 인상 생성은 모델 배정 표 밖에 둔다 — 턴이 부르는 단계가 아니라 요약 접기 몇 번마다 도는 백그라운드 작업이라 단계 표에 없고, 그래도
# 인상 모델을 Gemini 밖으로 바꾸면 Claude·판정 전용 체인의 인상 문안을 읽으므로 그 채널을 여기서 따로 합친다.
_CHANNELS_OUTSIDE_STAGE_TABLE = frozenset({"memory_impression"})
_JUDGMENT_CHANNELS_BY_LANE: dict[PromptLane, frozenset[str]] = {
    "story": stage_channels("story", "structured") | _CHANNELS_OUTSIDE_STAGE_TABLE,
    "character": stage_channels("character", "structured") | _CHANNELS_OUTSIDE_STAGE_TABLE,
    "publish_filter": frozenset(),
    "novel": frozenset(),
    "novel_screen": frozenset(),
}

# Gemini 가 아닌 체인은 그 모델이 쓸 수 있는 채널만 갖는다.
# - Claude 세트(sonnet·opus 체인): 채팅 레인은 생성의 `system`·`generation` 과 그 레인의 판정·요약 채널이다. 판정·요약 채널은
#   판정 모델을 그 모델로 바꿨을 때 읽는 문안이다(모델 배정 표의 행이 고른 체인, 행이 없으면 판정·요약 모델 설정 — 기본은
#   Gemini). `novel` 레인은 Gemini 표의 채널 전부다 — 화 생성·구성안 둘은 사용자가 고른 모델의 체인을 읽고, 지금 늘 Gemini 체인으로
#   부르는 경계 제안·문단 수정·여러 문단 수정·묶음 재검사도 고른 모델로 부를 수 있게 그 체인에 문안을 둔다. 화 생성·구성안이
#   붙이는 등급 규칙(`novelize_rating`)도 그 체인 세트에서 읽는다.
# - 판정 전용 세트(haiku 체인): 그 레인의 판정·요약 채널만. 그 id 로는 글을 쓰지 않는다.
# R-1 기대 집합은 같은 레인 Gemini 표에서 이 채널만 남긴 것이다(표를 따로 적지 않는다 — 슬롯이 늘면 체인이 함께 따라온다).
# 그래서 **판정·요약 슬롯을 더하거나 바꾸는 마이그레이션은 Gemini 체인뿐 아니라 Claude 체인(story·character × sonnet·opus)과
# 판정 전용 체인(story·character × haiku)도 다뤄야** 그 체인 게시가 "누락"으로 막히지 않는다. 레인마다 따로 두는 이유는 한
# 집합으로 두면 다른 레인의 체인 기대 집합이 비어 그 체인 게시가 영원히 R-1 에 막히기 때문이다. 심사 레인에는 Gemini 체인뿐이고
# 판정 전용 체인은 채팅 레인에만 있다(`_require_lane_model`).
_CLAUDE_SET_CHANNELS_BY_LANE: dict[PromptLane, frozenset[str]] = {
    "story": frozenset({"system", "generation"}) | _JUDGMENT_CHANNELS_BY_LANE["story"],
    "character": frozenset({"system", "generation"}) | _JUDGMENT_CHANNELS_BY_LANE["character"],
    "publish_filter": frozenset(),
    "novel": frozenset(_NOVEL_LANE_ROWS),
    "novel_screen": frozenset(),
}


def _expected_slots(lane: PromptLane, model: PromptSetModelId) -> dict[str, frozenset[tuple[str, str]]]:
    expected = _EXPECTED_SLOTS_BY_LANE[lane]
    if model == "gemini":
        return expected
    channels = _JUDGMENT_CHANNELS_BY_LANE[lane] if model == "haiku" else _CLAUDE_SET_CHANNELS_BY_LANE[lane]
    return {channel: slots for channel, slots in expected.items() if channel in channels}


def _freezes_novel_rows(lane: PromptLane, model: PromptSetModelId) -> bool:
    """얼린 소설 행이 있는 체인 — 채팅 레인의 Gemini 체인뿐이다(Claude 채팅 체인에는 처음부터 소설 행이 없다)."""
    return lane in ("story", "character") and model == "gemini"


def _require_lane_model(lane: PromptLane, model: PromptSetModelId) -> None:
    """심사 레인(발행 심사·노벨 텍스트 심사)은 Gemini 세트뿐이다 — 심사는 모델을 고르지 않는다. 판정 전용 체인은 채팅
    판정·요약 문안이라 스토리·캐릭터 레인에만 있다."""
    if lane in ("publish_filter", "novel_screen") and model != "gemini":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"rule": "lane-model", "message": "심사 레인에는 Gemini 세트만 있습니다."},
        )
    if model == "haiku" and lane not in ("story", "character"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"rule": "lane-model", "message": "판정 전용 세트는 스토리·캐릭터 레인에만 있습니다."},
        )


# R-2 — variant 전종이 반드시 있어야 하는 슬롯. story
# 레인에만 있다 — `template_instruction`/`base_content` 둘 다 story 레인 전용 슬롯이라,
# 안 쪼개면 character·publish_filter 레인은 그 `(channel, scope, slot)` 행 자체가 없어
# `present`가 빈 집합이 되고 `missing`이 required 전체가 되어 **영원히 게시할 수 없다**
# ("공허 통과"가 아니라 "레인 필터가 없으면 거부"다).
#
# `template_instruction`은 요청한 variant가 없으면 폴백할 기본(`variant=""`) 행 자체가
# 없어 슬롯째 조용히 드롭된다.
#
# `base_content`도 같은 크기의 사고다 — 처음엔 "기본 행이 있으니 드롭이 아니라 다른
# 문안으로 대체될 뿐"이라고 판단했는데 **틀렸다(적대적 리뷰가 실제 시드 body로 재현)**:
# `custom` variant가 빠지면 CUSTOM 템플릿 스토리도 `variant=""` 행(`body="{setting_text}"`)
# 으로 폴백하고, CUSTOM 스토리는 `setting_text`가 비어 있는 게 정상이라 `conditional=True`
# 탓에 섹션째 드롭된다 — "다른 문안으로 대체"가 아니라 **작품 설정(세계관/커스텀
# 프롬프트) 전체 소실**이다. `tests/test_chat_prompt_builder.py`의
# `test_render_prompt_channel_default_variant_fallback_drops_section_when_value_is_empty`가
# 이 사고를 렌더러 수준에서 고정한다.
#
# `StoryPromptTemplate`에서 직접 뽑아 두 벌로 갈릴 여지를 없앤다.
#
# 두 슬롯 모두 생성 채널에 있다 — 검사는 그 체인이 그 채널을 갖는 경우에만 한다(`_validate_prompt_draft_for_publish`). 레인
# 기준으로만 걸면 생성 채널이 없는 story 판정 전용 세트가 영원히 게시할 수 없다.
_REQUIRED_VARIANT_SLOTS_BY_LANE: dict[PromptLane, dict[tuple[str, str, str], frozenset[str]]] = {
    "story": {
        ("system", "story", "template_instruction"): frozenset(t.value for t in StoryPromptTemplate),
        ("generation", "story", "base_content"): frozenset({"", "custom"}),
    },
    "character": {},
    "publish_filter": {},
    "novel": {},
    "novel_screen": {},
}

# 레인마다 실제로 읽는 라벨만 검사한다. `ast`로 함수별
# 라벨 사용을 전수 추출해 도출했다: story={user,story_assistant,story_example} /
# character={user,character_assistant} / publish_filter=없음(발행 심사는 이미지 목록만 싣고 대화 줄을
# 조립하지 않는다) / novel={user,story_assistant,character_assistant}(소설 호출은 원문 줄 라벨을 소설 레인 세트에서 읽는다 —
# 스토리 원작은 진행자, 캐릭터 원작은 캐릭터 라벨. 읽는 것은 Gemini 체인 세트뿐이지만 세 체인이 같은 값을 갖게 함께 검사한다) / novel_screen=없음
# (텍스트 심사는 공개할 글만 싣고 대화 줄을 조립하지 않는다). 헤더 컬럼 4개는
# 레인과 무관하게 그대로 남는다.
_LABEL_FIELDS_BY_LANE: dict[PromptLane, tuple[tuple[str, str], ...]] = {
    "story": (
        ("userLabel", "user_label"),
        ("storyAssistantLabel", "story_assistant_label"),
        ("storyExampleLabel", "story_example_label"),
    ),
    "character": (
        ("userLabel", "user_label"),
        ("characterAssistantLabel", "character_assistant_label"),
    ),
    "publish_filter": (),
    "novel": (
        ("userLabel", "user_label"),
        ("storyAssistantLabel", "story_assistant_label"),
        ("characterAssistantLabel", "character_assistant_label"),
    ),
    "novel_screen": (),
}


def _validation_error(rule: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"rule": rule, "message": message})


def _validate_prompt_draft_for_publish(
    prompt_set: PromptSet, sections: list[PromptSection], *, lane: PromptLane, model: PromptSetModelId = "gemini"
) -> None:
    """R-1~R-8. 규칙
    이름이 붙은 순서대로 검사하고 첫 위반에서 멈춘다("순서대로 본다") — 뒤의 규칙들은
    앞이 통과했다는 것에 기대어 있다(예: R-2는 슬롯 자체가 있다는 R-1의 결과를 전제한다).
    `lane`은 키워드 전용이다 — 앞 두 인자가 위치 인자라 세 번째 위치 인자가 붙으면 순서
    실수가 조용히 통과할 여지가 있다. `model` 은 R-1 의 기대 집합만 바꾼다(`_expected_slots`)."""
    # R-1 — `variant`는 보지 않는다(위 `_EXPECTED_SLOTS_BY_LANE` 주석 참고, R-2와 역할을 가른다).
    grouped: dict[str, set[tuple[str, str]]] = {}
    for section in sections:
        grouped.setdefault(section.channel, set()).add((section.scope, section.slot))
    actual = {channel: frozenset(rows) for channel, rows in grouped.items()}
    expected = _expected_slots(lane, model)
    if actual != expected:
        raise _validation_error(
            "R-1", "슬롯 집합이 코드가 아는 목록과 다릅니다(누락 또는 잉여가 있습니다)."
        )

    # R-2 — 이 체인에 있는 채널의 슬롯만(위 `_REQUIRED_VARIANT_SLOTS_BY_LANE` 주석).
    for (channel, scope, slot), required_variants in _REQUIRED_VARIANT_SLOTS_BY_LANE[lane].items():
        if channel not in expected:
            continue
        present = {
            s.variant for s in sections if s.channel == channel and s.scope == scope and s.slot == slot
        }
        missing = required_variants - present
        if missing:
            raise _validation_error(
                "R-2", f"{channel}/{slot}에 variant가 빠졌습니다: {sorted(missing)}"
            )

    # R-3
    for section in sections:
        if not section.body.strip():
            raise _validation_error(
                "R-3", f"{section.channel}/{section.slot}(variant={section.variant!r})의 body가 비어 있습니다."
            )

    # R-4
    for section in sections:
        try:
            fields = [name for _, name, _, _ in Formatter().parse(section.body) if name is not None]
        except ValueError as exc:
            raise _validation_error(
                "R-4", f"{section.channel}/{section.slot} body의 중괄호 짝이 맞지 않습니다: {exc}"
            ) from exc
        allowed = ALLOWED_PLACEHOLDERS.get((section.channel, section.slot), frozenset())
        unknown = sorted({name for name in fields if name not in allowed})
        if unknown:
            raise _validation_error(
                "R-4", f"{section.channel}/{section.slot} body가 허용되지 않은 플레이스홀더를 씁니다: {unknown}"
            )

    # R-5
    for query_name, attr in _LABEL_FIELDS_BY_LANE[lane]:
        value = getattr(prompt_set, attr)
        if not value.strip():
            raise _validation_error("R-5", f"{query_name}이(가) 비어 있습니다.")
        if "\n" in value or ":" in value:
            raise _validation_error("R-5", f"{query_name}은(는) 개행이나 ':'을 포함할 수 없습니다.")

    # R-6. `(channel, scope, variant)`로 묶는다 — `self_definition`/`intro_instruction`처럼
    # 같은 슬롯이 scope만 다르게 두 행으로 존재하는 경우 서로 다른 실제 렌더 호출
    # (story-scope 렌더와 character-scope 렌더)에서만 각각 쓰이므로 같은 order를 공유해도
    # 충돌이 아니다 — 그래서 scope를 그룹 키에서 빼면 이 정상 케이스를 오탐한다. 이 사각
    # 지대는 R-8이 렌더 결과 쪽에서 다시 본다(scope가 달라도 렌더 선택에는 같이 들어갈
    # 수 있다).
    seen_orders: dict[tuple[str, str, str], dict[int, str]] = {}
    for section in sections:
        group = seen_orders.setdefault((section.channel, section.scope, section.variant), {})
        if section.order in group:
            raise _validation_error(
                "R-6",
                f"{section.channel}(scope={section.scope}, variant={section.variant!r})에서 "
                f"order={section.order}가 {group[section.order]!r}와 {section.slot!r}에 중복됩니다.",
            )
        group[section.order] = section.slot

    # R-7 — priority_tail은 both 행이라 `publish_filter` 레인에는 존재하지 않는다(그 레인엔
    # system 채널 자체가 없다). 기본값 없는 next()는 그 레인에서 StopIteration -> 500이었다.
    # `other_orders`가 비어 있을 때도 건드리지
    # 않는다 — tail 하나만 있고 비교 대상이 없으면 검사할 것이 없다.
    system_sections = [s for s in sections if s.channel == "system"]
    tail = next((s for s in system_sections if s.slot == "priority_tail"), None)
    if tail is not None:
        other_orders = [s.order for s in system_sections if s.slot != "priority_tail"]
        if other_orders and tail.order <= max(other_orders):
            raise _validation_error("R-7", "system 채널에서 priority_tail의 order가 가장 크지 않습니다.")

    # R-8 — R-6의 그룹 키에 scope가 들어 있어
    # (system, both, '', 5)와 (system, story, '', 5)를 **다른 그룹**으로 본다. 렌더러는
    # 둘을 한 리스트에 담아 안정 정렬하므로 동률이면 입력 순서가 출력을 정한다.
    # R-6을 고치는 것은 답이 아니다 — 그 scope는 self_definition의 정상 케이스를
    # 오탐하지 않으려고 들어간 것이다. R-8이 렌더 결과 쪽에서 같은 불변식을 다시 본다.
    # `select_sections_for_render`(chat/prompt_builder.py)는 렌더러(render_prompt_channel)와
    # 같은 함수다 — 사본을 두면 렌더러가 바뀔 때 R-8이 조용히 딴 것을 검사하게 된다.
    for channel in {s.channel for s in sections}:
        channel_sections = [s for s in sections if s.channel == channel]
        variants = {s.variant for s in channel_sections} | {""}
        for render_scope in ("story", "character"):
            for variant in sorted(variants):
                selected = select_sections_for_render(
                    channel_sections, channel=channel, scope=render_scope, variant=variant
                )
                orders = [s.order for s in selected]
                if len(orders) != len(set(orders)):
                    raise _validation_error(
                        "R-8",
                        f"{channel}(render_scope={render_scope}, variant={variant!r})에서 렌더 선택 "
                        "결과의 order가 중복됩니다.",
                    )


async def _next_published_version(db: AsyncSession) -> str:
    """서버가 부여하는 자동 증가 정수(문자열로 저장). 별도 함수로 뺀 이유는
    `test_admin_prompts_api.py`가 이 반환값만 몽키패치해 두 게시가 같은 버전을 계산하는
    경쟁을 흉내내기 위해서다(legal의 동시성 테스트가 `_get_draft`를 패치하는 것과 같은
    방식)."""
    latest_version: int | None = await db.scalar(
        select(func.max(cast(PromptSet.version, Integer))).where(PromptSet.status == "published")
    )
    return str((latest_version or 0) + 1)


async def _get_draft(
    db: AsyncSession, lane: PromptLane, model: PromptSetModelId, *, for_update: bool = False
) -> PromptSet | None:
    """`lane`이 없는 `db.scalar()`는 레인 필터가
    빠져도 조용히 첫 행을 반환한다 — `.scalars(...).one_or_none()`으로 두면 레인·모델 필터가
    빠졌을 때(부분 유니크 인덱스가 (레인, 모델)별이라 초안이 여러 행일 수 있다) `MultipleResultsFound`로
    시끄럽게 터진다.

    `for_update` 는 초안을 덮어쓰는 경로가 해시 검사와 교체 사이에 다른 저장이 끼어들지 못하게 행을 잠글 때 켠다. 잠근 뒤 값을
    다시 채워야(이미 세션에 올라온 객체라도) 기다리는 동안 커밋된 다른 저장을 본다."""
    query = select(PromptSet).where(PromptSet.status == "draft", PromptSet.lane == lane, PromptSet.model == model)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await db.scalars(query)).one_or_none()


async def _sections_of(db: AsyncSession, prompt_set_id: uuid.UUID) -> list[PromptSection]:
    sections = (
        await db.scalars(select(PromptSection).where(PromptSection.prompt_set_id == prompt_set_id))
    ).all()
    return sorted(sections, key=lambda s: (s.channel, s.order, s.slot, s.variant))


def _to_section_item(section: PromptSection) -> AdminPromptSectionItem:
    return AdminPromptSectionItem(
        channel=section.channel,
        scope=section.scope,
        slot=section.slot,
        variant=section.variant,
        body=section.body,
        conditional=section.conditional,
        order=section.order,
    )


async def _saved_draft_hash(db: AsyncSession, draft: PromptSet | None) -> str | None:
    """저장된 초안 행의 내용 해시(라벨 포함). 게시 경로와 같은 해시 함수를 쓰되 얼린 소설 행을 갈아 끼우지 않은, 저장된 그대로의
    내용이다 — 저장 요청이 돌려보낸 값과 견줄 때도 같은 내용을 봐야 하기 때문이다."""
    if draft is None:
        return None
    return draft_fingerprint(section_contents(draft, await _sections_of(db, draft.id)))


def _allowed_placeholder_hints(lane: PromptLane, model: PromptSetModelId) -> list[AdminPromptPlaceholderHint]:
    """이 체인이 편집할 수 있는 채널의 (채널, 슬롯)마다 쓸 수 있는 자리표시자. 값은 게시 검사가 쓰는 `ALLOWED_PLACEHOLDERS` 를
    그대로 쓴다(상수에 없는 슬롯은 게시 검사처럼 빈 목록). 채팅 Gemini 체인의 얼린 소설 채널은 화면에 싣지 않으므로 뺀다."""
    hidden = _NOVELIZE_CHANNELS if _freezes_novel_rows(lane, model) else frozenset()
    return [
        AdminPromptPlaceholderHint(
            channel=channel, slot=slot, names=sorted(ALLOWED_PLACEHOLDERS.get((channel, slot), frozenset()))
        )
        for channel, slots in sorted(_expected_slots(lane, model).items())
        if channel not in hidden
        for slot in sorted({slot for _scope, slot in slots})
    ]


async def _draft_response(
    db: AsyncSession,
    *,
    lane: PromptLane,
    model: PromptSetModelId,
    draft: PromptSet | None,
    rating_drift: list[AdminPromptRatingDrift] | None = None,
    dropped_channels: list[str] | None = None,
    filled_channels: list[str] | None = None,
) -> AdminPromptDraftResponse:
    """초안 응답을 만드는 유일한 자리 — 조회·저장·통째 복원·섹션 복원이 모두 여기를 거쳐 저장된 초안 해시와 허용 자리표시자
    힌트를 빠뜨리는 응답이 생기지 않게 한다. 초안 행이 없으면 그 체인의 활성 세트를 보여 준다(저장하지 않는다)."""
    if draft is not None:
        source: PromptSet = draft
        sections = await _sections_of(db, draft.id)
    else:
        source, sections = await load_active_prompt_set(db, lane=lane, model=model)
    return AdminPromptDraftResponse(
        id=draft.id if draft is not None else None,
        model=model,
        labels=_to_labels(source),
        sections=[_to_section_item(s) for s in _visible_sections(lane, model, sections)],
        saved_draft_hash=await _saved_draft_hash(db, draft),
        allowed_placeholders=_allowed_placeholder_hints(lane, model),
        rating_drift=rating_drift or [],
        dropped_channels=dropped_channels or [],
        filled_channels=filled_channels or [],
    )


_CHAT_RATING_CHANNEL = "system"
_RATING_NOVEL_MODELS: tuple[PromptSetModelId, ...] = ("gemini", "sonnet", "opus")


def _rating_md5(sections: list[PromptSection], *, channel: str, scope: str) -> str | None:
    rendered = render_rating(sections, channel=channel, scope=scope)
    return hashlib.md5(rendered.encode()).hexdigest() if rendered.strip() else None


async def rating_drift(
    db: AsyncSession, *, lane: PromptLane, model: PromptSetModelId, sections: list[PromptSection]
) -> list[AdminPromptRatingDrift]:
    """`sections`(게시하려는·복원한 그 체인의 섹션)의 등급 규칙을 같은 원작 종류의 다른 레인 활성판과 견준다. 막지 않고 알리기만
    한다 — 소설 등급 규칙은 채팅 값에서 옮겨 온 사본이라 한쪽만 고치면 두 레인의 수위 규칙이 조용히 갈린다.

    - 채팅 (story·character, gemini): 그 레인 scope 의 `system/rule_rating` 렌더 대 소설 세 체인 활성의 `novelize_rating` 같은
      scope 렌더.
    - 소설 (novel, 아무 체인): scope story 렌더 대 (story, gemini) 활성, scope character 렌더 대 (character, gemini) 활성.
    - 그 밖은 빈 목록이다. Claude 채팅 체인은 견주지 않는다 — 소설 등급 규칙의 원본은 채팅 Gemini 체인이다. 스토리와 캐릭터의
      등급 규칙끼리도 견주지 않는다(원작 종류마다 다른 규칙일 수 있다).
    렌더는 소설 빌더가 지시문 뒤에 붙이는 글과 같은 함수(`render_rating`)다."""
    pairs: list[tuple[Literal["story", "character"], PromptLane, PromptSetModelId, str, str]] = []
    if lane == "story" and model == "gemini":
        pairs = [("story", "novel", other, _CHAT_RATING_CHANNEL, RATING_CHANNEL) for other in _RATING_NOVEL_MODELS]
    elif lane == "character" and model == "gemini":
        pairs = [("character", "novel", other, _CHAT_RATING_CHANNEL, RATING_CHANNEL) for other in _RATING_NOVEL_MODELS]
    elif lane == "novel":
        pairs = [
            ("story", "story", "gemini", RATING_CHANNEL, _CHAT_RATING_CHANNEL),
            ("character", "character", "gemini", RATING_CHANNEL, _CHAT_RATING_CHANNEL),
        ]
    items: list[AdminPromptRatingDrift] = []
    for scope, other_lane, other_model, this_channel, other_channel in pairs:
        try:
            other_set, other_sections = await load_active_prompt_set(db, lane=other_lane, model=other_model)
        except PromptSetNotFoundError:
            continue
        this_md5 = _rating_md5(sections, channel=this_channel, scope=scope)
        other_md5 = _rating_md5(other_sections, channel=other_channel, scope=scope)
        items.append(
            AdminPromptRatingDrift(
                scope=scope,
                other_lane=other_lane,
                other_model=other_model,
                other_set_id=other_set.id,
                this_md5=this_md5,
                other_md5=other_md5,
                differs=this_md5 != other_md5,
            )
        )
    return items


def _draft_changed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "rule": "draft-changed",
            "message": "편집을 연 뒤 다른 곳에서 초안이 저장됐습니다. 새로 불러온 뒤 다시 고쳐 주세요.",
        },
    )


def _to_labels(prompt_set: PromptSet) -> AdminPromptLabels:
    return AdminPromptLabels(
        user_label=prompt_set.user_label,
        story_assistant_label=prompt_set.story_assistant_label,
        story_example_label=prompt_set.story_example_label,
        character_assistant_label=prompt_set.character_assistant_label,
    )


@dataclass(frozen=True)
class _SectionFields:
    channel: str
    scope: str
    slot: str
    variant: str
    body: str
    conditional: bool
    order: int


def _section_fields(section: PromptSection) -> _SectionFields:
    return _SectionFields(
        channel=section.channel,
        scope=section.scope,
        slot=section.slot,
        variant=section.variant,
        body=section.body,
        conditional=section.conditional,
        order=section.order,
    )


async def _active_frozen_novel_sections(db: AsyncSession, lane: PromptLane) -> list[PromptSection]:
    """채팅 레인 Gemini 활성 세트의 얼린 소설 행."""
    _, active_sections = await load_active_prompt_set(db, lane=lane)
    return [s for s in active_sections if s.channel in _NOVELIZE_CHANNELS]


def _visible_sections(
    lane: PromptLane, model: PromptSetModelId, sections: list[PromptSection]
) -> list[PromptSection]:
    """초안 응답에 싣는 섹션. 채팅 Gemini 체인에서는 얼린 소설 행을 뺀다 — 소설 문안은 소설 탭에서만 고치고, 화면이 받지
    않은 행은 저장 때 서버가 다시 채운다(`_replace_draft_content`)."""
    if not _freezes_novel_rows(lane, model):
        return sections
    return [s for s in sections if s.channel not in _NOVELIZE_CHANNELS]


def _find_duplicate_section_keys(sections: list[_SectionFields]) -> list[tuple[str, str, str, str]]:
    """`(channel, scope, slot, variant)` 중복을 찾는다 — DB의 유니크 인덱스
    (`ix_prompt_sections_set_channel_scope_slot_variant`)와 같은 키다.

    적대적 리뷰가 재현한 결함: 이 검사 없이 SAVEPOINT에 그대로 들어가면, 요청 자신의
    섹션 목록에 중복 키가 있어도 "다른 요청이 먼저 커밋했다"는 경쟁 상황과 **똑같은**
    `IntegrityError`가 난다. 초안이 없던 경우엔 SAVEPOINT 롤백이 방금 만든 draft 행까지
    되감아 `except` 블록의 `assert draft is not None`이 깨지고, 초안이 있던 경우엔
    `except` 블록의 재삽입이 감싸이지 않은 채 그대로 크래시한다 — 두 원인이 같은
    예외로 오므로 사후에 구분하려 들지 않고, 애초에 SAVEPOINT 밖에서 요청 자체를
    검사해 걸러낸다."""
    seen: set[tuple[str, str, str, str]] = set()
    duplicates: list[tuple[str, str, str, str]] = []
    for item in sections:
        key = (item.channel, item.scope, item.slot, item.variant)
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    return duplicates


async def _replace_draft_content(
    db: AsyncSession,
    *,
    lane: PromptLane,
    model: PromptSetModelId,
    labels: AdminPromptLabels,
    sections: list[_SectionFields],
    check_base_hash: bool = False,
    base_draft_hash: str | None = None,
) -> PromptSet:
    """초안 upsert — 섹션 전체 교체다. `PUT /{lane}/draft`와 `POST /{id}/restore`가
    공유한다.

    `check_base_hash` 를 켜면 이 (레인, 모델)의 초안 행을 잠근 뒤 저장된 초안 해시가 `base_draft_hash` 와 같을 때만 덮어쓰고, 다르면
    아무것도 쓰지 않고 409 `draft-changed` 다(`base_draft_hash` 가 None 이면 "초안 행이 없어야 한다"). 화면이 연 뒤 다른 탭이
    저장한 초안을 조용히 덮지 않으려는 것이다. 끄면(해시를 모르는 옛 화면, 자체 409 확인이 있는 섹션 복원) 검사하지 않는다.
    초안이 없던 두 요청이 동시에 첫 초안을 만들면 잠글 행이 없어 둘 다 검사를 통과하므로, 검사를 켠 진 쪽은 아래 경쟁 복구로
    이긴 행을 덮지 않고 409 를 낸다.

    `admin/legal.py`의 SAVEPOINT 패턴을 그대로 따른다: 세션이 이미 이 요청(또는 테스트의
    롤백 트랜잭션)이라는 바깥 트랜잭션 안에 있으므로 `db.rollback()`은 그 바깥까지 되감아
    이전에 커밋된 행까지 지운다(실측으로 확인, `admin/legal.py:139-153`) — 이 upsert
    하나만 되감으려면 `begin_nested()`(SAVEPOINT)가 필요하다. 두 요청이 동시에 이 레인의
    초안이 없는 것을 보고 경쟁하면 진 쪽의 INSERT가 부분 유니크 인덱스(`ix_prompt_sets_draft`,
    레인별)에 걸리는데, upsert 의미상 "이 레인의 초안이 이 내용이 되게 하라"는 먼저 커밋된
    게 자신인지 남인지와 무관하게 그대로 성립하므로 409로 거부하지 않고 이긴 행을 다시
    읽어 이 요청의 내용으로 덮어쓴다(legal의 draft upsert와 같은 판단). 자식(섹션) 삭제→삽입도
    같은 SAVEPOINT 안에서 한다 — `relationship()`이 없어 순서를 직접 지켜야 한다.

    `try`/`except IntegrityError` 두 블록 모두
    `_get_draft(db, lane, model)`로 **이 (레인, 모델)의** 초안만 찾고, `delete(PromptSection)` 직전에
    레인·모델 assert 를 둔다. 한쪽만 고치면 정상 경로는 멀쩡한데 경쟁 상황에서만
    다른 체인 초안의 섹션이 통째로 삭제될 수 있다 — 재현 난이도가 가장 높은 부류의
    데이터 소실이라 코드 리뷰로 두 블록을 각각 확인해야 한다.

    채팅 Gemini 체인이면 들어온 소설 행(`novelize_*`)을 버리고 활성 세트의 소설 행으로 갈아 끼운다. 소설 문안은 `novel`
    레인으로 옮겼고 채팅 레인의 소설 행은 옛 이미지로 되돌렸을 때 옛 코드가 읽는 값이라 바뀌면 안 된다 — 배포 전부터 열린
    편집 탭이 그 행을 보내도, 소설 행이 다른 옛 버전을 복원해도 얼린 값이 그대로 남는다."""
    if _freezes_novel_rows(lane, model):
        frozen = await _active_frozen_novel_sections(db, lane)
        sections = [item for item in sections if item.channel not in _NOVELIZE_CHANNELS] + [
            _section_fields(section) for section in frozen
        ]
    duplicate_keys = _find_duplicate_section_keys(sections)
    if duplicate_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "rule": "duplicate-section-key",
                "message": f"섹션 키(channel, scope, slot, variant)가 중복됩니다: {duplicate_keys}",
            },
        )

    draft = await _get_draft(db, lane, model, for_update=True)
    if check_base_hash and await _saved_draft_hash(db, draft) != base_draft_hash:
        raise _draft_changed()
    try:
        async with db.begin_nested():
            if draft is None:
                draft = PromptSet(
                    id=uuid.uuid4(),
                    version=None,
                    status="draft",
                    lane=lane,
                    model=model,
                    note="",
                    user_label=labels.user_label,
                    story_assistant_label=labels.story_assistant_label,
                    story_example_label=labels.story_example_label,
                    character_assistant_label=labels.character_assistant_label,
                )
                db.add(draft)
                await db.flush()
            else:
                draft.user_label = labels.user_label
                draft.story_assistant_label = labels.story_assistant_label
                draft.story_example_label = labels.story_example_label
                draft.character_assistant_label = labels.character_assistant_label

            assert draft.lane == lane and draft.model == model  # 이 (레인, 모델)의 초안만 지운다
            await db.execute(delete(PromptSection).where(PromptSection.prompt_set_id == draft.id))
            await db.flush()
            for item in sections:
                db.add(
                    PromptSection(
                        id=uuid.uuid4(),
                        prompt_set_id=draft.id,
                        channel=item.channel,
                        scope=item.scope,
                        slot=item.slot,
                        variant=item.variant,
                        body=item.body,
                        conditional=item.conditional,
                        order=item.order,
                    )
                )
            await db.flush()
    except IntegrityError:
        if check_base_hash:
            # 위 검사는 초안이 없을 때 통과했다 — 화면은 초안이 없다고 믿었는데 다른 요청이 먼저 만들었다.
            raise _draft_changed() from None
        draft = await _get_draft(db, lane, model, for_update=True)
        assert draft is not None  # 유니크 위반은 곧 이 (레인, 모델)의 초안이 이제 존재한다는 뜻이다
        draft.user_label = labels.user_label
        draft.story_assistant_label = labels.story_assistant_label
        draft.story_example_label = labels.story_example_label
        draft.character_assistant_label = labels.character_assistant_label
        assert draft.lane == lane and draft.model == model  # except 복구 경로도 이 (레인, 모델)의 초안만 지운다
        await db.execute(delete(PromptSection).where(PromptSection.prompt_set_id == draft.id))
        await db.flush()
        for item in sections:
            db.add(
                PromptSection(
                    id=uuid.uuid4(),
                    prompt_set_id=draft.id,
                    channel=item.channel,
                    scope=item.scope,
                    slot=item.slot,
                    variant=item.variant,
                    body=item.body,
                    conditional=item.conditional,
                    order=item.order,
                )
            )

    await db.commit()
    return draft


async def _sections_to_publish(
    db: AsyncSession, draft: PromptSet, *, lane: PromptLane, model: PromptSetModelId
) -> list[PromptSection]:
    """게시할 섹션 — 초안 섹션에서 채팅 Gemini 체인의 얼린 소설 행만 활성판 값으로 갈아 끼운 것. 게시와 바뀐 섹션 조회가 함께
    쓴다."""
    sections = await _sections_of(db, draft.id)
    if _freezes_novel_rows(lane, model):
        # 초안을 저장할 때 이미 얼린 값으로 갈아 끼우지만, 이 규칙 전에 저장된 초안도 있다 — 게시하는 값은 늘 직전
        # 게시본의 소설 행이다(`_replace_draft_content` 와 같은 이유).
        frozen = await _active_frozen_novel_sections(db, lane)
        sections = sorted(
            [s for s in sections if s.channel not in _NOVELIZE_CHANNELS] + frozen,
            key=lambda s: (s.channel, s.order, s.slot, s.variant),
        )
    return sections


def _semver_conflict(rule: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"rule": rule, "message": message})


async def _plan_publish_semver(
    db: AsyncSession,
    body: AdminPromptPublishRequest,
    *,
    lane: PromptLane,
    model: PromptSetModelId,
    contents: dict[str, tuple[object, ...]],
) -> SemverPlan:
    """게시의 판을 아무것도 쓰기 전에 계산한다. 화면이 바뀐 섹션 조회 때 받은 기준판·초안 해시를 돌려보냈으면 지금 값과 견주어,
    그 사이 다른 게시나 초안 저장이 끼어들었으면 409 로 멈춘다(단계를 다시 고르게). 보내지 않은 화면은 견주지 않는다."""
    base = await load_base(db, lane, model)
    if body.draft_hash is not None and body.draft_hash != draft_fingerprint(contents):
        raise _semver_conflict(
            "semver-draft-changed", "변경 내역을 본 뒤 초안이 바뀌었습니다. 바뀐 섹션을 다시 확인해 주세요."
        )
    if "base_set_id" in body.model_fields_set and body.base_set_id != (base.set_id if base is not None else None):
        raise _semver_conflict(
            "semver-base-moved", "변경 내역을 본 뒤 다른 게시가 먼저 들어왔습니다. 바뀐 섹션을 다시 확인해 주세요."
        )
    try:
        return plan_semver(base, contents, body.levels)
    except SemverLevelError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "rule": "semver-level-for-unchanged-section",
                "message": f"바뀌지 않았거나 없는 섹션에 판 단계를 골랐습니다: {error.names}",
            },
        ) from None


# ---- 목록·조회 ----------------------------------------------------------------


# `{lane}` 라우트의 모델은 쿼리 `?model=`(기본 gemini)로 받는다 — 경로 세그먼트를 늘리지 않아 아래 `/{id}` 충돌
# 규약이 그대로이고, 모델을 모르는 옛 어드민 화면도 그대로 Gemini 세트를 편집한다.
_MODEL_QUERY = Query("gemini", description="세트 체인의 모델(글쓰기 모델 또는 판정 전용 id). 생략하면 Gemini 세트다.")


@router.get("/admin/prompt-sets/{lane}/draft")
async def get_prompt_draft(
    lane: PromptLane,
    model: PromptSetModelId = _MODEL_QUERY,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    """라우트 순서 규약. `/{lane}/draft`는 세그먼트가 2개,
    `GET /admin/prompt-sets/{id}`는 1개라 정규식이 겹치지 않아 등록 순서와 무관하게 둘 다
    도달 가능하다. **`GET /admin/prompt-sets/{lane}`(1세그먼트) 라우트는 만들지 않는다** —
    만들면 `GET /{id}`와 정규식이 글자 그대로 같아져 한쪽이 도달 불가가 되고, 정상 요청이
    404가 아니라 422를 받는다(`{id}`가 먼저 등록돼 있으면 레인 문자열의 UUID 파싱 실패)."""
    _require_lane_model(lane, model)
    return await _draft_response(db, lane=lane, model=model, draft=await _get_draft(db, lane, model))


@router.put("/admin/prompt-sets/{lane}/draft")
async def upsert_prompt_draft(
    lane: PromptLane,
    body: AdminPromptDraftUpsertRequest,
    model: PromptSetModelId = _MODEL_QUERY,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    _require_lane_model(lane, model)
    fields = [
        _SectionFields(
            channel=item.channel,
            scope=item.scope,
            slot=item.slot,
            variant=item.variant,
            body=item.body,
            conditional=item.conditional,
            order=item.order,
        )
        for item in body.sections
    ]
    draft = await _replace_draft_content(
        db,
        lane=lane,
        model=model,
        labels=body.labels,
        sections=fields,
        check_base_hash="base_draft_hash" in body.model_fields_set,
        base_draft_hash=body.base_draft_hash,
    )
    return await _draft_response(db, lane=lane, model=model, draft=draft)


@router.post("/admin/prompt-sets/{lane}/draft/preview")
async def preview_prompt_draft(
    lane: PromptLane,
    model: PromptSetModelId = _MODEL_QUERY,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptPreviewResponse:
    """샘플 입력으로 **실제 렌더러**를 태워 조립된 전문을 채널별로 돌려준다.
    LLM은 부르지 않는다. 이 레인의 초안이 없으면 이 레인의 활성 세트로 미리보기한다
    (`GET .../draft`와 같은 폴백)."""
    _require_lane_model(lane, model)
    draft = await _get_draft(db, lane, model)
    if draft is not None:
        prompt_set = draft
        sections = await _sections_of(db, draft.id)
    else:
        prompt_set, sections = await load_active_prompt_set(db, lane=lane, model=model)

    # 소설 호출은 원문 줄 라벨을 소설 레인 Gemini 체인 세트에서 읽는다 — 미리보기도 실호출과 같은 세트로(Gemini 초안이면 그 초안의
    # 라벨을 보여 준다).
    label_set = None
    if lane == "novel":
        label_set = prompt_set if model == "gemini" else await load_novel_label_set(db)
    items = _build_preview_items(prompt_set, sections, lane=lane, model=model, label_set=label_set)
    return AdminPromptPreviewResponse(items=items)


@router.get("/admin/prompt-sets/{lane}/draft/changes")
async def get_prompt_draft_changes(
    lane: PromptLane,
    model: PromptSetModelId = _MODEL_QUERY,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftChangesResponse:
    """게시하면 판이 어떻게 갈릴지 미리 본다(읽기만 한다). 계산은 게시와 같은 함수다 — 얼린 소설 행 갈아 끼우기까지 같아야
    화면이 단계를 고르게 한 섹션과 실제로 올라가는 섹션이 같다. 경로가 세그먼트 3개라 `GET /{id}` 와 겹치지 않는다."""
    _require_lane_model(lane, model)
    draft = await _get_draft(db, lane, model)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="발행할 초안이 없습니다.")
    to_publish = await _sections_to_publish(db, draft, lane=lane, model=model)
    contents = section_contents(draft, to_publish)
    base = await load_base(db, lane, model)
    changes = (
        diff_sections(contents, None)
        if base is None
        else diff_sections(contents, base.contents, unnumbered=base.unnumbered)
    )
    return AdminPromptDraftChangesResponse(
        base_set_id=base.set_id if base is not None else None,
        base_semver=format_semver(base.number) if base is not None else None,
        draft_hash=draft_fingerprint(contents),
        sections=[
            AdminPromptSectionChange(
                channel=channel,
                change=change,
                current_semver=(
                    format_semver(base.section_numbers[channel])
                    if base is not None and channel in base.section_numbers
                    else None
                ),
            )
            for channel, change in sorted(changes.items())
        ],
        rating_drift=await rating_drift(db, lane=lane, model=model, sections=to_publish),
    )


@router.post("/admin/prompt-sets/{lane}/publish")
async def publish_prompt_set(
    lane: PromptLane,
    body: AdminPromptPublishRequest,
    model: PromptSetModelId = _MODEL_QUERY,
    admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptSetDetailResponse:
    _require_lane_model(lane, model)
    draft = await _get_draft(db, lane, model)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="발행할 초안이 없습니다.")
    sections = await _sections_to_publish(db, draft, lane=lane, model=model)

    _validate_prompt_draft_for_publish(draft, sections, lane=lane, model=model)
    plan = await _plan_publish_semver(db, body, lane=lane, model=model, contents=section_contents(draft, sections))

    # 레인·모델 필터가 없다("안 넣는 것"이 결정이다). 버전 문자열 하나가 "언제 게시됐는가"를
    # 전역 시간축 위에 놓는다 — story의 v3 다음 게시가 v5일 수 있다(중간 v4는 다른 레인이나 다른 모델의 게시).
    next_version = await _next_published_version(db)

    # `admin/legal.py:139-153`과 같은 이유로 `begin_nested()`(SAVEPOINT)로 감싼다 — 두
    # 게시가 동시에 같은 `next_version`을 계산하면 부분 유니크 인덱스
    # (`ix_prompt_sets_version_published`)가 뒤에 커밋되는 쪽을 막는데, 그건 진짜 초안
    # upsert와 달리 "덮어써도 되는" 경쟁이 아니라 서로 다른 두 내용 중 하나를 잃는
    # 상황이라 409로 재시도를 요구한다.
    try:
        async with db.begin_nested():
            published = PromptSet(
                id=uuid.uuid4(),
                version=next_version,
                status="published",
                lane=lane,
                model=model,
                note=body.note,
                user_label=draft.user_label,
                story_assistant_label=draft.story_assistant_label,
                story_example_label=draft.story_example_label,
                character_assistant_label=draft.character_assistant_label,
                published_at=datetime.now(UTC),
            )
            db.add(published)
            await db.flush()
            for section in sections:
                db.add(
                    PromptSection(
                        id=uuid.uuid4(),
                        prompt_set_id=published.id,
                        channel=section.channel,
                        scope=section.scope,
                        slot=section.slot,
                        variant=section.variant,
                        body=section.body,
                        conditional=section.conditional,
                        order=section.order,
                    )
                )
            await db.flush()
            # 판 행도 같은 SAVEPOINT 안이다 — 같은 기준판을 읽은 다른 게시가 먼저 커밋했으면 기준판 유니크(또는 체인 번호
            # 유니크)에 걸려 위 정수 번호 경합과 같은 409 가 된다. 셋 다 "다시 시도"가 답이라 문구를 나누지 않는다.
            await write_semver(db, prompt_set_id=published.id, lane=lane, model=model, plan=plan)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="방금 다른 게시와 버전이 겹쳤습니다. 다시 시도해 주세요.",
        ) from None

    await record_admin_action(
        db,
        admin_id=admin_id,
        action_type="prompt-set-publish",
        reason_text=body.note,
    )
    # legal과 같다 — 게시 후에도 초안 행은 지우지 않는다(오타 하나 고쳐 재게시하는 흐름).
    await db.commit()

    # ⚠️ 반드시 커밋 **뒤에** 무효화한다 — 커밋 전에 지우면
    # 그 사이의 캐시 미스가 아직 커밋되지 않은(=옛) 값을 다시 캐싱해 이 게시가 통째로
    # 씹힌다. `invalidate_active_prompt_set`은 `RedisError`를 삼키지 않는데, 여기서는
    # 그걸 삼키고 경고만 남긴다 — **DB 커밋(진짜 소스)이 이미 성공했다는 것은 곧 게시가
    # 실제로 일어났다는 뜻이다.** 이 시점에 500을 올리면 이미 일어난 성공을 실패로
    # 잘못 알리는 것이다. TTL(`prompt_set_cache_ttl_seconds`)이 이 실패의 상한이라 최대
    # 그 시간만큼만 옛 문안이 나간다 — DB read/SET 캐시 모듈이 이미 쓰는 것과 같은 판단이다.
    try:
        await invalidate_active_prompt_set(lane, model=model)
    except RedisError:
        logger.warning("게시 후 프롬프트 세트 캐시 무효화 실패", exc_info=True)
        # 낡은 프롬프트가 TTL만큼 계속 나가는 신호라 이벤트로도 남긴다.
        capture_dependency_failure(dependency="redis")

    return AdminPromptSetDetailResponse(
        id=published.id,
        lane=lane,
        model=model,
        version=published.version,
        status=published.status,
        note=published.note,
        created_at=published.created_at,
        published_at=published.published_at,
        labels=_to_labels(published),
        sections=[_to_section_item(s) for s in sections],
        semver=format_semver(plan.number),
        section_semvers=[
            AdminPromptSectionSemver(channel=channel, semver=format_semver(number), level=level)
            for channel, (number, level) in sorted(plan.sections.items())
        ],
        removed_sections=plan.removed,
        rating_drift=await rating_drift(db, lane=lane, model=model, sections=sections),
    )


@router.post("/admin/prompt-sets/{id}/restore")
async def restore_prompt_set(
    id: uuid.UUID,
    body: AdminPromptSetRestoreRequest | None = None,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    """옛 버전을 초안으로 복제한다(= 롤백 경로). 게시하지 않는 한 서비스에는 아무 영향이
    없다 — 실제 롤백은 이 뒤에 이어지는 `POST /publish`가 한다.

    레인·모델은 요청에서 따로 받지 않는다 — `source.lane`·`source.model`에서만 나온다(그 체인의 초안으로 들어간다).
    `source.lane`이 `legacy`(레인 분리 과도기의 격리 값)면 422로 거부한다 — 레인
    분리 이전 버전은 복원 대상이 아니다.

    본문은 생략할 수 있다(옛 화면). `base_draft_hash` 를 보내면 초안 저장과 같이 그 사이 다른 탭이 저장한 초안을 덮지 않는다."""
    source = await db.get(PromptSet, id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 버전을 찾을 수 없습니다.")
    lane = as_prompt_lane(source.lane)
    if lane is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "rule": "legacy-lane",
                "message": "레인 분리 이전 버전은 복원할 수 없습니다.",
            },
        )
    model = parse_prompt_set_model_id(source.model)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"rule": "unknown-model", "message": "지금은 없는 모델의 버전은 복원할 수 없습니다."},
        )
    source_sections = await _sections_of(db, source.id)

    # 그 체인이 지금 갖는 채널 집합으로 맞춘다 — 채널이 늘거나 준 뒤의 옛 판을 그대로 옮기면 초안 게시가 슬롯 집합 검사(R-1)에
    # "누락"·"잉여"로 막히고, 화면에는 채널을 지우는 손이 없다. 남는 채널은 버리고 빠진 채널은 그 체인 활성판에서 채운다.
    expected = _expected_slots(lane, model)
    source_channels = {s.channel for s in source_sections}
    dropped = sorted(source_channels - set(expected))
    missing = sorted(set(expected) - source_channels)
    fields = [_section_fields(s) for s in source_sections if s.channel in expected]
    if missing:
        _, active_sections = await load_active_prompt_set(db, lane=lane, model=model)
        fields += [_section_fields(s) for s in active_sections if s.channel in missing]
    # 채팅 Gemini 체인의 얼린 소설 채널은 어차피 저장 때 활성판 값으로 갈아 끼우므로 채운 채널로 알리지 않는다.
    hidden = _NOVELIZE_CHANNELS if _freezes_novel_rows(lane, model) else frozenset()
    filled = [channel for channel in missing if channel not in hidden]
    draft = await _replace_draft_content(
        db,
        lane=lane,
        model=model,
        labels=_to_labels(source),
        sections=fields,
        check_base_hash=body is not None and "base_draft_hash" in body.model_fields_set,
        base_draft_hash=body.base_draft_hash if body is not None else None,
    )
    return await _draft_response(
        db,
        lane=lane,
        model=model,
        draft=draft,
        rating_drift=await rating_drift(db, lane=lane, model=model, sections=await _sections_of(db, draft.id)),
        dropped_channels=dropped,
        filled_channels=filled,
    )


@router.post("/admin/prompt-sets/{id}/sections/{channel}/restore")
async def restore_prompt_section(
    id: uuid.UUID,
    channel: str,
    body: AdminPromptSectionRestoreRequest,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptDraftResponse:
    """옛 게시본의 섹션 하나(채널 하나 또는 화자 라벨 넷 묶음 `speaker_labels`)만 그 체인의 초안으로 가져온다. 통째 복원은 다른
    채널의 게시 안 한 편집까지 옛 값으로 돌리므로, 한 채널만 되돌릴 때 이 라우트를 쓴다. 게시하지 않는다 — 복원한 섹션은 다음
    게시에서 기준판과 다른 섹션으로 잡혀 새 번호로 오른다(옛 번호로 돌아가지 않는다).

    체인은 원본 세트의 (레인, 모델)이다. 거절은 모두 아무것도 쓰기 전에 한다. 초안이 없으면 활성판을 바탕으로 초안을 만든다
    (`GET /draft` 와 같은 폴백). 그 섹션의 초안 내용이 활성판과 다르면(게시 안 한 편집이 있으면) 요청이 덮어쓰기를 켜지 않은 한
    409 다. 경로가 세그먼트 4개라 `/{id}/restore`·`/{lane}/draft` 와 겹치지 않는다."""
    source = await db.get(PromptSet, id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 버전을 찾을 수 없습니다.")
    if source.status != "published":
        raise _validation_error("restore-source-not-published", "초안은 되돌릴 판이 아닙니다. 게시된 버전을 고르세요.")
    lane = as_prompt_lane(source.lane)
    if lane is None:
        raise _validation_error("legacy-lane", "레인 분리 이전 버전은 복원할 수 없습니다.")
    model = parse_prompt_set_model_id(source.model)
    if model is None:
        raise _validation_error("unknown-model", "지금은 없는 모델의 버전은 복원할 수 없습니다.")

    source_sections = await _sections_of(db, source.id)
    is_labels = channel == SPEAKER_LABELS
    source_rows = [s for s in source_sections if s.channel == channel]
    if not is_labels:
        if not source_rows:
            raise _validation_error("restore-channel-not-in-source", f"그 버전에는 '{channel}' 섹션이 없습니다.")
        expected = _expected_slots(lane, model)
        if channel not in expected:
            raise _validation_error("restore-channel-not-in-chain", f"이 체인에는 '{channel}' 섹션이 없습니다.")
        if _freezes_novel_rows(lane, model) and channel in _NOVELIZE_CHANNELS:
            raise _validation_error(
                "restore-frozen-channel",
                "채팅 레인의 소설 섹션은 게시 때 지금 값으로 고정되므로 복원할 수 없습니다. 소설 레인에서 고치세요.",
            )
        source_slots = {(s.scope, s.slot) for s in source_rows}
        if source_slots != expected[channel]:
            raise _validation_error(
                "restore-slots-mismatch",
                f"그 버전의 '{channel}' 슬롯이 지금과 다릅니다(빠진 슬롯 {sorted(expected[channel] - source_slots)}, "
                f"남는 슬롯 {sorted(source_slots - expected[channel])}).",
            )

    draft = await _get_draft(db, lane, model)
    if draft is not None:
        base_set: PromptSet = draft
        base_sections = await _sections_of(db, draft.id)
        active_set, active_sections = await load_active_prompt_set(db, lane=lane, model=model)
        draft_contents = section_contents(draft, base_sections)
        active_contents = section_contents(active_set, active_sections)
        if draft_contents.get(channel) != active_contents.get(channel) and not body.overwrite_draft_changes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "rule": "draft-channel-has-unpublished-edits",
                    "message": f"초안의 '{channel}' 섹션에 게시하지 않은 편집이 있습니다. 덮어쓰려면 덮어쓰기를 켜고 다시 "
                    "요청하세요.",
                },
            )
    else:
        base_set, base_sections = await load_active_prompt_set(db, lane=lane, model=model)

    if is_labels:
        labels = _to_labels(source)
        fields = [_section_fields(s) for s in base_sections]
    else:
        labels = _to_labels(base_set)
        fields = [_section_fields(s) for s in base_sections if s.channel != channel] + [
            _section_fields(s) for s in source_rows
        ]
    saved = await _replace_draft_content(db, lane=lane, model=model, labels=labels, sections=fields)
    return await _draft_response(
        db,
        lane=lane,
        model=model,
        draft=saved,
        rating_drift=await rating_drift(db, lane=lane, model=model, sections=await _sections_of(db, saved.id)),
    )


@router.get("/admin/prompt-sets/{id}")
async def get_prompt_set(
    id: uuid.UUID,
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptSetDetailResponse:
    prompt_set = await db.get(PromptSet, id)
    lane = as_prompt_lane(prompt_set.lane) if prompt_set is not None else None
    model = parse_prompt_set_model_id(prompt_set.model) if prompt_set is not None else None
    if prompt_set is None or lane is None or model is None:
        # `lane`이 `legacy`면 응답의 `lane: PromptLane`을 채울 수 없다 — 새
        # 코드는 legacy를 읽지 않는다는 원칙을 그대로 따라 404로 취급한다. 레지스트리에서 내린 모델도 같다.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 버전을 찾을 수 없습니다.")
    sections = await _sections_of(db, prompt_set.id)
    return AdminPromptSetDetailResponse(
        id=prompt_set.id,
        lane=lane,
        model=model,
        version=prompt_set.version,
        status=prompt_set.status,
        note=prompt_set.note,
        created_at=prompt_set.created_at,
        published_at=prompt_set.published_at,
        labels=_to_labels(prompt_set),
        sections=[_to_section_item(s) for s in sections],
        semver=(await semvers_of(db, [prompt_set.id])).get(prompt_set.id),
        section_semvers=[
            AdminPromptSectionSemver(channel=channel, semver=format_semver(number), level=level)
            for channel, number, level in await section_semvers_of(db, prompt_set.id)
        ],
    )


@router.get("/admin/prompt-sets")
async def list_prompt_sets(
    _admin_id: uuid.UUID = Depends(get_current_admin_id),
    db: AsyncSession = Depends(get_db_session),
) -> AdminPromptSetListResponse:
    prompt_sets = (
        await db.scalars(select(PromptSet).order_by(PromptSet.created_at.desc()))
    ).all()
    # (레인, 모델)마다 "현재 활성본" 하나씩 — DISTINCT ON 으로 고른다.
    active_ids = {
        prompt_set.id
        for prompt_set in (
            await db.scalars(
                select(PromptSet)
                .where(PromptSet.status == "published")
                .distinct(PromptSet.lane, PromptSet.model)
                .order_by(PromptSet.lane, PromptSet.model, PromptSet.published_at.desc(), PromptSet.id.desc())
            )
        ).all()
    }
    semvers = await semvers_of(db, [prompt_set.id for prompt_set in prompt_sets])
    items: list[AdminPromptSetSummary] = []
    for prompt_set in prompt_sets:
        lane = as_prompt_lane(prompt_set.lane)
        model = parse_prompt_set_model_id(prompt_set.model)
        if lane is None or model is None:
            continue  # legacy(레인 분리 과도기의 격리 값)와 레지스트리에서 내린 모델의 세트는 목록에서 뺀다.
        items.append(
            AdminPromptSetSummary(
                id=prompt_set.id,
                lane=lane,
                model=model,
                version=prompt_set.version,
                status=prompt_set.status,
                note=prompt_set.note,
                created_at=prompt_set.created_at,
                published_at=prompt_set.published_at,
                is_active=prompt_set.id in active_ids,
                semver=semvers.get(prompt_set.id),
            )
        )
    return AdminPromptSetListResponse(items=items)


# ---- 미리보기 샘플 입력 --------------------------------------------------------
#
# 별도 조립 코드를 만들지 않는다 — 위 `build_*` 함수들(실제 채팅·발행 검열이
# 쓰는 바로 그 함수)에 지어낸 샘플 값을 넣어 호출할 뿐이다. DB에 닿지 않는 순수 함수라
# (`chat/stats.py` 류와 같은 리포 관례) ORM 모델을 세션 없이 생성자로만 채운다.

_SAMPLE_HISTORY = [
    ChatMessage(role=ChatMessageRole.USER, content="[샘플] 오늘 하루 어땠어?"),
    ChatMessage(role=ChatMessageRole.ASSISTANT, content="[샘플] 그럭저럭. 네가 오니까 낫네."),
]
_SAMPLE_EXAMPLE_DIALOGUES = [{"userLine": "[샘플] 뭐 하고 있었어?", "characterLine": "[샘플] 너 기다리고 있었지."}]
_SAMPLE_DEVELOPMENT_EXAMPLES = [{"userLine": "[샘플] 이 방향으로 가보자", "assistantLine": "[샘플] 그러자, 앞장설게"}]
# 비우면 conditional 드롭으로 섹션이 안 보여 운영자가
# `user_persona` 문안이 어떻게 렌더되는지 볼 수 없다. 실채팅과 같은 조립 함수를 거친다.
_SAMPLE_USER_PERSONA = format_user_persona(
    name="[샘플] 하늘", gender="female", description="[샘플] 밤하늘을 좋아하는 대학생"
)


@dataclass(frozen=True)
class _SamplePromptNames(PromptNames):
    """미리보기 전용 이름 묶음 — 모든 이름 자리를 샘플 이름으로 채운다.

    이름 한 줄도 비우면 conditional 드롭으로 안 보인다(위 프로필과 같은 이유). 실채팅의 생성 채널은 이름 한 줄을 늘
    비우고 판정·요약은 프로필이 없으면 비우지만, 미리보기는 운영자가 생성·판정·요약 채널의 이름 문안을 다 보게 세 자리를
    모두 샘플 이름으로 덮는다. 프로필 섹션 값은 위 샘플을 그대로 넘긴다 — 생성 미리보기에 두 섹션이 함께 보이는 것은
    미리보기에서만이다. 실채팅 클래스에 미리보기용 필드를 두지 않으려고 여기서만 덮는다."""

    sample_user_name: str = "[샘플] 하늘"

    def expand(self, text: str) -> str:
        return expand_author_macros(text, user_name=self.sample_user_name, char_name=self.char_name)

    @property
    def judgment_user_name(self) -> str:
        return self.sample_user_name

    @property
    def generation_user_name(self) -> str:
        return self.sample_user_name


_SAMPLE_STORY_NAMES = _SamplePromptNames(persona_name=None, char_name=None)
_SAMPLE_CHARACTER_NAMES = _SamplePromptNames(persona_name=None, char_name="[샘플] 캐릭터")
# 기억 슬롯도 비우면 conditional 드롭으로 안 보인다(위 프로필과 같은 이유).
_SAMPLE_MEMORY_NOTE = "[샘플] 주인공의 여동생 이름은 서연이다."
_SAMPLE_MEMORY_SUMMARY = "[샘플] 두 사람은 비 오는 밤 편의점에서 처음 만났고, 다음 주에 다시 보기로 약속했다."
# 요약 비밀 표기 슬롯의 인물 이름 목록. 실채팅은 스위치가 켜졌을 때만 채우지만, 비우면 conditional 드롭으로 문안이 안 보인다.
_SAMPLE_ROOM_PEOPLE = ["[샘플] 민아", "[샘플] 준호"]
# 회상 섹션과 추출 호출의 앞 구간 장면 제목도 비우면 conditional 드롭으로 안 보인다(위 프로필과 같은 이유). 회상 줄은 실채팅의
# 줄 모양(`- 제목: 내용`, 인물이 한 말이면 꼬리표)을 흉내 낸다.
_SAMPLE_MEMORY_RECALL_LINES = "- [샘플] 빵집 약속: [샘플] 토요일 열한 시에 소금빵을 사 오기로 했다. (인물의 말)"
_SAMPLE_PREVIOUS_EPISODE_TITLES = ["[샘플] 비 오는 밤 편의점"]
# 사실 섹션 줄과 사실 추출의 기존 키 줄도 채운다 — 비우면 사실 섹션은 conditional 드롭으로 안 보이고, 기존 키는 "(없음)"만
# 보인다. 사실 줄은 실채팅의 줄 모양(관계는 `주어 → 대상: 값`, 사실은 `주어: 값`, 꼬리표)을, 기존 키 줄은 추출 문안이 말하는
# `종류|주어|대상 또는 속성 = 값 (상태)` 꼴을 흉내 낸다.
_SAMPLE_MEMORY_FACT_LINES = (
    "- [샘플] 세빈 → 사용자: 경계를 풀었다\n"
    "- [샘플] 유나: 겨울 오디션 준비 (사용자만 앎)\n"
    "- (사실 아님으로 밝혀짐) [샘플] 도희: 생일이 삼월\n"
    "- [샘플] 도희: 생일이 오월 (도희의 말)\n"
    "- [샘플] 사용자: 고양이를 키운다 (사용자의 말)"
)
_SAMPLE_EXISTING_FACTS = ["relation|[샘플] 세빈|[샘플] 하늘 = 경계 — 말을 아낌 (confirmed)"]
# 인상 생성의 입력 줄. 비우면 두 섹션이 conditional 드롭으로 안 보인다. 인상 작업이 만드는 줄 모양(장면은 `- 제목: 내용`, 관계는
# `- 주어 → 대상: 값 (상태)`, 속성은 `- 주어 / 속성: 값 (상태)`)을 흉내 낸다.
_SAMPLE_IMPRESSION_EPISODE_LINES = ["- [샘플] 비 오는 밤 편의점: [샘플] 세빈이 우산을 건네고 먼저 자리를 떴다."]
_SAMPLE_IMPRESSION_FACT_LINES = [
    "- [샘플] 세빈 → [샘플] 하늘: 경계·신뢰 — 말을 아끼다 우산을 건넴 (confirmed)",
    "- [샘플] 하늘 / 진로 계획: 겨울 오디션 준비 (claimed)",
]
_SAMPLE_STAT_DEFS = [
    StatDef(
        entity_id=uuid.uuid4(),
        starting_setup_id=uuid.uuid4(),
        name="호감도",
        icon="heart",
        color="#ff6b81",
        min_value=0,
        max_value=100,
        initial_value=50,
        unit=None,
        description="[샘플] 캐릭터가 사용자에게 느끼는 호감도",
        per_turn_delta=None,
        order=1,
    )
]
# 규칙 판정 미리보기의 샘플 규칙 — 오르는 규칙과 내리는 규칙 하나씩(폭은 프롬프트에 실리지 않는다).
_SAMPLE_STAT_RULES = {
    _SAMPLE_STAT_DEFS[0].entity_id: [
        StatRule(entity_id=uuid.uuid4(), condition="[샘플] 사용자가 캐릭터를 감싸 준다", delta=5, order=0),
        StatRule(entity_id=uuid.uuid4(), condition="[샘플] 사용자의 거짓말이 들킨다", delta=-10, order=1),
    ]
}
_SAMPLE_SITUATIONAL_IMAGES = [
    SituationalImage(
        entity_id=uuid.uuid4(),
        content_version_id=uuid.uuid4(),
        trigger_condition="[샘플] 캐릭터가 웃을 때",
        order=1,
    )
]
# 상황 설명이 있는 칸과 없는 칸 — 후보 줄이 두 모양으로 나간다.
_SAMPLE_MEDIA_CELLS = [
    MediaCellCandidate(
        entity_id=uuid.uuid4(), person="[샘플] 민아", scene="[샘플] 창가", situation_description="[샘플] 창가에서 웃는다"
    ),
    MediaCellCandidate(entity_id=uuid.uuid4(), person="[샘플] 민아", scene="[샘플] 교실", situation_description=""),
]
# 발행 심사 이미지 목록의 칸 라벨 — 인물·장면 이름만 쓴다.
_SAMPLE_MEDIA_BOOK_FILTER_CELLS = [
    MediaBookFilterCell(person="[샘플] 민아", scene="[샘플] 창가"),
    MediaBookFilterCell(person="[샘플] 민아", scene="[샘플] 옥상"),
]


def _memory_summary_preview_item(
    prompt_set: PromptSet, sections: list[PromptSection], *, is_story_chat: bool, names: PromptNames
) -> AdminPromptPreviewItem:
    """요약 호출 프롬프트. 직전 요약이 있는 경우(두 번째 접기부터)와 비밀 표기 슬롯이 켜진 경우를 보여 준다 — 비우면 그
    섹션이 드롭돼 운영자가 문안을 못 본다."""
    return AdminPromptPreviewItem(
        channel="memory_summary",
        label="memory_summary",
        text=build_memory_summary_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story_chat,
            previous_summary=_SAMPLE_MEMORY_SUMMARY,
            turns=_SAMPLE_HISTORY,
            names=names,
            room_people=_SAMPLE_ROOM_PEOPLE,
        ),
    )


def _memory_fact_preview_item(
    prompt_set: PromptSet, sections: list[PromptSection], *, is_story_chat: bool, names: PromptNames
) -> AdminPromptPreviewItem:
    """관계·사실 기억 추출 호출 프롬프트. 기존 키가 있는 경우(두 번째 접기부터)를 보여 준다 — 비우면 "(없음)"만 보여 운영자가
    키 줄이 어떻게 실리는지 못 본다."""
    return AdminPromptPreviewItem(
        channel="memory_fact",
        label="memory_fact",
        text=build_memory_fact_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story_chat,
            existing_facts=_SAMPLE_EXISTING_FACTS,
            turns=_SAMPLE_HISTORY,
            names=names,
        ),
    )


def _memory_episode_preview_item(
    prompt_set: PromptSet, sections: list[PromptSection], *, is_story_chat: bool, names: PromptNames
) -> AdminPromptPreviewItem:
    """장면 기억 추출 호출 프롬프트. 앞 구간이 있는 경우(두 번째 접기부터)를 보여 준다 — 비우면 그 섹션이 드롭돼 운영자가
    문안을 못 본다."""
    return AdminPromptPreviewItem(
        channel="memory_episode",
        label="memory_episode",
        text=build_memory_episode_prompt(
            prompt_set=prompt_set,
            sections=sections,
            is_story_chat=is_story_chat,
            previous_titles=_SAMPLE_PREVIOUS_EPISODE_TITLES,
            turns=_SAMPLE_HISTORY,
            names=names,
        ),
    )


def _memory_impression_preview_item(
    sections: list[PromptSection], *, is_story_chat: bool
) -> AdminPromptPreviewItem:
    """인상 생성 호출 프롬프트. 장면·사실 줄이 둘 다 있는 경우를 보여 준다 — 비우면 그 섹션이 드롭돼 운영자가 문안을 못 본다."""
    return AdminPromptPreviewItem(
        channel="memory_impression",
        label="memory_impression",
        text=build_memory_impression_prompt(
            sections=sections,
            is_story_chat=is_story_chat,
            episode_lines=_SAMPLE_IMPRESSION_EPISODE_LINES,
            fact_lines=_SAMPLE_IMPRESSION_FACT_LINES,
        ),
    )


# 소설화 샘플 — 조건부 섹션(설정 노트·인물 메모·지난 화 요약·앞 화의 끝)도 문안이 보이게 채운다. 원문 줄은 빌더
# docstring 의 형식을 따른다.
_SAMPLE_NOVELIZE_TURN_LINES = (
    "[턴 1] {assistant}: [샘플] 왔어?\n[턴 2] {user}: [샘플] 응, 늦어서 미안.\n[턴 2] {assistant}: [샘플] 괜찮아."
)
_SAMPLE_NOVELIZE_PARAGRAPHS = ["[샘플] 첫 문단", "[샘플] 둘째 문단", "[샘플] 셋째 문단"]
# 구성 흐름의 장면 계획과 맥락으로만 보내는 구간(원문 줄과 같은 형식).
_SAMPLE_NOVELIZE_SCENE_PLAN = "[샘플] 1. 비 오는 정류장에서 다시 만난다(턴 1~2)."
_SAMPLE_BLOCK_EDIT_LINES = "[1] [샘플] 첫 문단.\n\n[2] [샘플] 둘째 문단.\n\n[3] [샘플] 셋째 문단."
_SAMPLE_NOVELIZE_CONTEXT_LINES = "[턴 1] {assistant}: [샘플] 지난번 일은 잊어."

# 소설 원작의 종류 = 등급 규칙 행의 scope·원문 줄 라벨을 고르는 축.
_NovelContentLane = Literal["story", "character"]
_NOVEL_CONTENT_LANES: tuple[_NovelContentLane, ...] = ("story", "character")
_NOVEL_CONTENT_LABELS: dict[_NovelContentLane, str] = {"story": "스토리", "character": "캐릭터"}


def _novelize_preview_item(channel: str, label: str, build: Callable[[], NovelizePrompt]) -> AdminPromptPreviewItem:
    """소설 채널 행이 빠진 초안(다른 레인 세트를 붙여 넣은 경우 등)이면 빌더가 렌더를 거부한다. 그 한 항목만 안내로
    바꿔 나머지 미리보기는 그대로 보여 준다(행이 빠진 초안의 게시는 슬롯 검사가 따로 막는다)."""
    try:
        built = build()
    except PromptRenderError as exc:
        text = f"이 초안으로는 이 채널을 미리 볼 수 없습니다 — 소설화 문안이 없거나 렌더에 필요한 행이 비어 있습니다.\n({exc})"
    else:
        text = f"{built.system_instruction}\n\n{built.prompt}"
    return AdminPromptPreviewItem(channel=channel, label=label, text=text)


def _novel_preview_items(sections: list[PromptSection], *, label_set: PromptSet) -> list[AdminPromptPreviewItem]:
    """`novel` 레인. 원작 종류(스토리·캐릭터)마다 이 세트의 등급 규칙 행(scope story·character)과 `label_set`(소설 레인 Gemini 체인
    세트 — Gemini 초안이면 그 초안 자신)의 라벨로 일곱 채널을 렌더한다. 세 체인 모두 일곱 채널을 갖는다. 실호출은 지시문(뒤에 등급
    규칙)과 본문을 따로 보내지만 미리보기는 그 순서대로 이어 보여 준다."""
    items: list[AdminPromptPreviewItem] = []
    for content in _NOVEL_CONTENT_LANES:
        items.extend(_novel_content_preview_items(sections, content=content, label_set=label_set))
    return items


def _novel_content_preview_items(
    sections: list[PromptSection],
    *,
    content: _NovelContentLane,
    label_set: PromptSet,
) -> list[AdminPromptPreviewItem]:
    items: list[AdminPromptPreviewItem] = []
    is_story_chat = content == "story"
    suffix = _NOVEL_CONTENT_LABELS[content]
    assistant = label_set.story_assistant_label if is_story_chat else label_set.character_assistant_label
    turn_lines = _SAMPLE_NOVELIZE_TURN_LINES.format(user=label_set.user_label, assistant=assistant)
    items.append(
        _novelize_preview_item(
            "novelize_boundary",
            f"novelize_boundary · {suffix}",
            lambda: build_novelize_boundary_prompt(
                label_set=label_set,
                sections=sections,
                is_story_chat=is_story_chat,
                max_turns=2,
                user_name="[샘플] 하늘",
                turn_lines=turn_lines,
            ),
        )
    )
    items.append(
        _novelize_preview_item(
            "novelize_chapter",
            f"novelize_chapter · {suffix}",
            lambda: build_novelize_chapter_prompt(
                label_set=label_set,
                sections=sections,
                is_story_chat=is_story_chat,
                work_setting="[샘플] 작품 설정",
                user_name="[샘플] 하늘",
                setting_notes="[샘플] 설정 노트",
                previous_excerpt="[샘플] 앞 화의 마지막 문단",
                turn_lines=turn_lines,
                character_notes="[샘플] 도윤(윤이): 소꿉친구다.",
                previous_summaries="[샘플] 1화: 두 사람이 비 오는 밤 처음 만났다.",
                episode_count=2,
                novel_title_rule="[샘플] 이번에는 소설 제목도 쓴다.",
                scene_plan=_SAMPLE_NOVELIZE_SCENE_PLAN,
                context_lines=_SAMPLE_NOVELIZE_CONTEXT_LINES.format(assistant=assistant),
            ),
        )
    )
    items.append(
        _novelize_preview_item(
            "novelize_outline",
            f"novelize_outline · {suffix}",
            lambda: build_novelize_outline_prompt(
                label_set=label_set,
                sections=sections,
                is_story_chat=is_story_chat,
                work_setting="[샘플] 작품 설정",
                user_name="[샘플] 하늘",
                setting_notes="[샘플] 설정 노트",
                turn_lines=turn_lines,
                max_episodes=6,
                episode_hint=3,
                character_notes="[샘플] 도윤(윤이): 소꿉친구다.",
                previous_summaries="[샘플] 1화: 두 사람이 비 오는 밤 처음 만났다.",
                context_lines=_SAMPLE_NOVELIZE_CONTEXT_LINES.format(assistant=assistant),
            ),
        )
    )
    items.append(
        _novelize_preview_item(
            "novelize_episode_outline",
            f"novelize_episode_outline · {suffix}",
            lambda: build_novelize_episode_outline_prompt(
                label_set=label_set,
                sections=sections,
                is_story_chat=is_story_chat,
                work_setting="[샘플] 작품 설정",
                user_name="[샘플] 하늘",
                setting_notes="[샘플] 설정 노트",
                episode_outline="[샘플] 2화 · 빗속의 약속 — 두 사람이 정류장에서 다시 만난다.",
                turn_lines=turn_lines,
                character_notes="[샘플] 도윤(윤이): 소꿉친구다.",
                previous_summaries="[샘플] 1화: 두 사람이 비 오는 밤 처음 만났다.",
                context_lines=_SAMPLE_NOVELIZE_CONTEXT_LINES.format(assistant=assistant),
            ),
        )
    )
    items.append(
        _novelize_preview_item(
            "novelize_revise",
            f"novelize_revise · {suffix}",
            lambda: build_novelize_revise_prompt(
                sections=sections,
                is_story_chat=is_story_chat,
                work_setting="[샘플] 작품 설정",
                setting_notes="[샘플] 설정 노트",
                paragraphs=_SAMPLE_NOVELIZE_PARAGRAPHS,
                first_index=1,
                last_index=1,
                user_request="[샘플] 더 긴장감 있게",
            ),
        )
    )
    items.append(
        _novelize_preview_item(
            "novelize_revise_blocks",
            f"novelize_revise_blocks · {suffix}",
            lambda: build_novelize_revise_blocks_prompt(
                sections=sections,
                is_story_chat=is_story_chat,
                work_setting="[샘플] 작품 설정",
                setting_notes="[샘플] 설정 노트",
                paragraph_lines=_SAMPLE_BLOCK_EDIT_LINES,
                target_labels=[1, 3],
                user_request="[샘플] 더 긴장감 있게",
            ),
        )
    )
    items.append(
        _novelize_preview_item(
            "novelize_revise_recheck",
            f"novelize_revise_recheck · {suffix}",
            lambda: build_novelize_revise_recheck_prompt(
                sections=sections,
                is_story_chat=is_story_chat,
                edited_lines="[1] [샘플] 사용자가 직접 고친 첫 문단.",
                patch_lines="[3] [샘플] 수정안이 고친 셋째 문단.",
                paragraph_lines=_SAMPLE_BLOCK_EDIT_LINES,
            ),
        )
    )
    return items


def _story_preview_items(
    prompt_set: PromptSet, sections: list[PromptSection], *, channels: frozenset[str]
) -> list[AdminPromptPreviewItem]:
    """`channels` 에 있는 채널의 항목만 만든다(`_preview_channels`)."""
    items: list[AdminPromptPreviewItem] = []

    if "system" in channels:
        for template in StoryPromptTemplate:
            items.append(
                AdminPromptPreviewItem(
                    channel="system",
                    label=f"system · 스토리 · {template.value}",
                    text=system_instruction_for(sections, is_story_chat=True, template=template),
                )
            )

    if "generation" in channels:
        for label_suffix, template, custom_prompt in (
            ("스토리 · basic", StoryPromptTemplate.BASIC, None),
            ("스토리 · custom", StoryPromptTemplate.CUSTOM, "[샘플] 커스텀 프롬프트"),
        ):
            items.append(
                AdminPromptPreviewItem(
                    channel="generation",
                    label=f"generation · {label_suffix}",
                    text=build_story_generation_prompt(
                        prompt_set=prompt_set,
                        sections=sections,
                        prompt_template=template,
                        setting_text="[샘플] 세계관 설정" if custom_prompt is None else None,
                        development_examples=_SAMPLE_DEVELOPMENT_EXAMPLES,
                        user_goal="[샘플] 사용자의 목표",
                        rules="[샘플] 규칙",
                        custom_prompt=custom_prompt,
                        prologue="[샘플] 시작 상황",
                        history=_SAMPLE_HISTORY,
                        user_message="[샘플] 사용자 메시지",
                        user_persona=_SAMPLE_USER_PERSONA,
                        memory_note=_SAMPLE_MEMORY_NOTE,
                        memory_summary=_SAMPLE_MEMORY_SUMMARY,
                        keyword_note_texts=["[샘플] 키워드북 항목"],
                        situation_note_texts=["[샘플] 상황 노트"],
                        shortcut_prompt=None,
                        names=_SAMPLE_STORY_NAMES,
                        memory_recall_lines=_SAMPLE_MEMORY_RECALL_LINES,
                        memory_fact_lines=_SAMPLE_MEMORY_FACT_LINES,
                    ),
                )
            )

    if "stat_rule_judgment" in channels:
        rule_judgment_text, _ = build_stat_rule_judgment_prompt(
            prompt_set=prompt_set,
            sections=sections,
            stat_defs=_SAMPLE_STAT_DEFS,
            rules_by_stat_id=_SAMPLE_STAT_RULES,
            user_message="[샘플] 사용자 메시지",
            assistant_message="[샘플] 진행자 응답",
            names=_SAMPLE_STORY_NAMES,
        )
        items.append(
            AdminPromptPreviewItem(channel="stat_rule_judgment", label="stat_rule_judgment", text=rule_judgment_text)
        )
    if "scene_judgment" in channels:
        items.append(
            AdminPromptPreviewItem(
                channel="scene_judgment",
                label="scene_judgment",
                text=build_scene_judgment_prompt(
                    prompt_set=prompt_set,
                    sections=sections,
                    previous_place="[샘플] 직전 장소",
                    previous_time="[샘플] 직전 시간",
                    user_message="[샘플] 사용자 메시지",
                    assistant_message="[샘플] 진행자 응답",
                    names=_SAMPLE_STORY_NAMES,
                ),
            )
        )
    if "ending_judgment" in channels:
        items.append(
            AdminPromptPreviewItem(
                channel="ending_judgment",
                label="ending_judgment",
                text=_build_ending_judgment_prompt(
                    prompt_set=prompt_set,
                    sections=sections,
                    judgment_prompt="[샘플] 엔딩 판정 기준",
                    history=_SAMPLE_HISTORY,
                    user_message="[샘플] 사용자 메시지",
                    assistant_message="[샘플] 진행자 응답",
                    memory_summary=_SAMPLE_MEMORY_SUMMARY,
                    names=_SAMPLE_STORY_NAMES,
                ),
            )
        )
    if "image_judgment" in channels:
        items.append(
            AdminPromptPreviewItem(
                channel="image_judgment",
                label="image_judgment",
                text=_build_image_judgment_prompt(
                    prompt_set=prompt_set,
                    sections=sections,
                    scope="story",
                    assistant_label=prompt_set.story_assistant_label,
                    image_lines=media_cell_image_lines(_SAMPLE_MEDIA_CELLS, names=_SAMPLE_STORY_NAMES),
                    history=_SAMPLE_HISTORY,
                    user_message="[샘플] 사용자 메시지",
                    assistant_message="[샘플] 진행자 응답",
                    names=_SAMPLE_STORY_NAMES,
                ),
            )
        )
    if "memory_summary" in channels:
        items.append(
            _memory_summary_preview_item(prompt_set, sections, is_story_chat=True, names=_SAMPLE_STORY_NAMES)
        )
    if "memory_episode" in channels:
        items.append(
            _memory_episode_preview_item(prompt_set, sections, is_story_chat=True, names=_SAMPLE_STORY_NAMES)
        )
    if "memory_fact" in channels:
        items.append(
            _memory_fact_preview_item(prompt_set, sections, is_story_chat=True, names=_SAMPLE_STORY_NAMES)
        )
    if "memory_impression" in channels:
        items.append(_memory_impression_preview_item(sections, is_story_chat=True))
    # 얼린 소설 행은 미리보지 않는다 — 소설 문안은 `novel` 레인 미리보기에서 본다.

    return items


def _character_preview_items(
    prompt_set: PromptSet, sections: list[PromptSection], *, channels: frozenset[str]
) -> list[AdminPromptPreviewItem]:
    """`channels` 는 `_story_preview_items` 와 같다."""
    items: list[AdminPromptPreviewItem] = []

    if "system" in channels:
        items.append(
            AdminPromptPreviewItem(
                channel="system",
                label="system · 캐릭터",
                text=system_instruction_for(sections, is_story_chat=False),
            )
        )
    if "generation" in channels:
        items.append(
            AdminPromptPreviewItem(
                channel="generation",
                label="generation · 캐릭터",
                text=build_generation_prompt(
                    prompt_set=prompt_set,
                    sections=sections,
                    character_prompt="[샘플] 캐릭터 프롬프트",
                    example_dialogues=_SAMPLE_EXAMPLE_DIALOGUES,
                    history=_SAMPLE_HISTORY,
                    user_message="[샘플] 사용자 메시지",
                    user_persona=_SAMPLE_USER_PERSONA,
                    memory_note=_SAMPLE_MEMORY_NOTE,
                    memory_summary=_SAMPLE_MEMORY_SUMMARY,
                    names=_SAMPLE_CHARACTER_NAMES,
                    memory_recall_lines=_SAMPLE_MEMORY_RECALL_LINES,
                    memory_fact_lines=_SAMPLE_MEMORY_FACT_LINES,
                ),
            )
        )
    if "image_judgment" in channels:
        items.append(
            AdminPromptPreviewItem(
                channel="image_judgment",
                label="image_judgment",
                text=_build_image_judgment_prompt(
                    prompt_set=prompt_set,
                    sections=sections,
                    scope="character",
                    assistant_label=prompt_set.character_assistant_label,
                    image_lines=situational_image_lines(_SAMPLE_SITUATIONAL_IMAGES, names=_SAMPLE_CHARACTER_NAMES),
                    history=_SAMPLE_HISTORY,
                    user_message="[샘플] 사용자 메시지",
                    assistant_message="[샘플] 캐릭터 응답",
                    names=_SAMPLE_CHARACTER_NAMES,
                ),
            )
        )
    if "memory_summary" in channels:
        items.append(
            _memory_summary_preview_item(prompt_set, sections, is_story_chat=False, names=_SAMPLE_CHARACTER_NAMES)
        )
    if "memory_episode" in channels:
        items.append(
            _memory_episode_preview_item(prompt_set, sections, is_story_chat=False, names=_SAMPLE_CHARACTER_NAMES)
        )
    if "memory_fact" in channels:
        items.append(
            _memory_fact_preview_item(prompt_set, sections, is_story_chat=False, names=_SAMPLE_CHARACTER_NAMES)
        )
    if "memory_impression" in channels:
        items.append(_memory_impression_preview_item(sections, is_story_chat=False))

    return items


def _publish_filter_preview_items(sections: list[PromptSection]) -> list[AdminPromptPreviewItem]:
    items: list[AdminPromptPreviewItem] = []

    # ⚠️ 이 두 label 문자열을 다듬지 않는다. 응답에 scope 필드가 없어
    # "· 캐릭터"/"· 스토리" 구분이 오직 label에만 있다.
    items.append(
        AdminPromptPreviewItem(
            channel="publish_filter",
            label="publish_filter · 캐릭터",
            text=build_character_publish_filter_prompt(
                sections=sections, situational_image_count=len(_SAMPLE_SITUATIONAL_IMAGES)
            ),
        )
    )
    items.append(
        AdminPromptPreviewItem(
            channel="publish_filter",
            label="publish_filter · 스토리",
            text=build_story_publish_filter_prompt(sections=sections, media_cells=_SAMPLE_MEDIA_BOOK_FILTER_CELLS),
        )
    )

    return items


# 텍스트 심사 미리보기의 샘플 — 처음 공개(소설 제목·소개)와 1화 하나를 함께 심사하는 꼴이다.
_SAMPLE_NOVEL_SCREEN_ITEMS: tuple[NovelScreenItem, ...] = (
    NovelScreenItem(part="novel_title", text="[샘플] 소설 제목"),
    NovelScreenItem(part="synopsis", text="[샘플] 소설 소개"),
    NovelScreenItem(part="chapter_title", text="[샘플] 1화 제목"),
    NovelScreenItem(part="author_note", text="[샘플] 작가의 말"),
    NovelScreenItem(part="chapter_body", text="[샘플] 첫 문단이다.\n\n[샘플] 둘째 문단이다."),
)


def _novel_screen_preview_items(sections: list[PromptSection]) -> list[AdminPromptPreviewItem]:
    """지시문(system_instruction)과 본문을 한 항목으로 잇는다 — 소설화 미리보기와 같은 꼴. 심사 채널 행이 빠진 초안이면
    빌더가 렌더를 거부하므로 안내로 바꾼다(그런 초안의 게시는 슬롯 검사가 따로 막는다)."""
    try:
        built = build_novel_screen_prompt(sections, _SAMPLE_NOVEL_SCREEN_ITEMS)
    except PromptRenderError as exc:
        text = f"이 초안으로는 텍스트 심사를 미리 볼 수 없습니다 — 심사 문안이 없거나 렌더에 필요한 행이 비어 있습니다.\n({exc})"
    else:
        text = f"{built.system_instruction}\n\n{built.prompt}"
    return [AdminPromptPreviewItem(channel="novel_screen", label="novel_screen · 텍스트 심사", text=text)]


def _preview_channels(lane: PromptLane, model: PromptSetModelId, sections: list[PromptSection]) -> frozenset[str]:
    """채팅 레인 미리보기가 렌더할 채널 — 그 체인이 갖는 채널이다. Gemini 체인은 지금처럼 전부다. 다른 체인은 그 체인
    기대 채널 중 초안에 실제로 있는 것만이다: 판정 전용 세트에는 생성 행이 없고, 판정·요약 행을 심기 전의 Claude 버전을
    복원한 초안에는 판정·요약 행이 없다 — 없는 채널을 렌더하면 빌더가 렌더를 거부한다(그런 초안의 게시는 슬롯 검사가 막는다)."""
    expected = frozenset(_expected_slots(lane, model))
    if model == "gemini":
        return expected
    return expected & {section.channel for section in sections}


def _build_preview_items(
    prompt_set: PromptSet,
    sections: list[PromptSection],
    *,
    lane: PromptLane,
    model: PromptSetModelId,
    label_set: PromptSet | None = None,
) -> list[AdminPromptPreviewItem]:
    """`label_set` 은 `novel` 레인에서만 쓴다 — 원문 줄 라벨을 읽을 소설 레인 Gemini 체인 세트."""
    if lane == "story":
        return _story_preview_items(prompt_set, sections, channels=_preview_channels(lane, model, sections))
    if lane == "character":
        return _character_preview_items(prompt_set, sections, channels=_preview_channels(lane, model, sections))
    if lane == "novel":
        assert label_set is not None  # 호출부(`preview_prompt_draft`)가 novel 레인이면 읽어 넘긴다
        return _novel_preview_items(sections, label_set=label_set)
    if lane == "novel_screen":
        return _novel_screen_preview_items(sections)
    return _publish_filter_preview_items(sections)
