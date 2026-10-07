"""소설화 호출 세 개(묶음 경계 제안·화 생성·문단 수정)의 프롬프트 빌더. 문안은 `novel` 레인 프롬프트 세트의
`novelize_*` 채널에 있고(스토리·캐릭터 원작이 같은 행을 `scope="both"` 로 함께 쓴다), 코드는 값만 만든다. 화 생성은
작업의 모델 체인 세트를, 경계 제안과 문단 수정은 Gemini 체인 세트를 읽는다(`inputs.load_novel_prompt_source`).

각 채널의 `instruction` 슬롯만 `system_instruction` 으로 보내고 나머지 슬롯은 본문으로 보낸다. 원문·작품 설정·
설정 노트·수정 요청은 사용자나 작가가 쓴 글이라 지시처럼 읽힐 수 있어, 역할 규칙을 그 글과 다른 통로에 두려는 것이다
(대화 생성의 `system` 채널과 같은 배치). 화 생성과 문단 수정은 지시문 뒤에 **채팅 레인** Gemini 활성 세트의
`system/rule_rating` 본문을 붙이고, 원문 줄의 화자 라벨도 그 세트에서 읽는다 — 등급 규칙과 라벨을 소설 레인에 복사하면
어드민에서 두 곳을 따로 고쳐야 하는 사본이 되고, Claude 채팅 세트에는 등급 규칙이 따로 손질돼 있을 수 있어 소스를
하나로 둔다. 소설 문안은 그 행의 머리말 `[수위]` 를 이름으로 가리키므로, 머리말을 바꾸면 소설 지시문도 같이 본다.

**빈 프롬프트로 과금 호출을 내지 않는다.** 렌더러는 섹션이 하나도 없으면 빈 문자열을 낸다. 소설 채널 행이 빠진 세트나
등급 규칙 행이 없는 채팅 세트, 옮길 원문·고칠 문단이 빈 입력이면 호출 전에 `PromptRenderError` 를 낸다. 호출부는 이
실패를 차감 전 거절 또는 환불로 처리한다. 소설화는 활성 세트 캐시를 쓰지 않고 매번 DB 를 읽는다."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from api.chat.prompt_builder import PromptRenderError, render_prompt_channel, select_sections_for_render
from api.core.config import settings
from api.db.models.prompt import PromptSection, PromptSet

_INSTRUCTION_SLOT = "instruction"

# 채널마다 값이 비어도 렌더되는(conditional 이 아닌) 슬롯 — 하나라도 없으면 그 세트로는 호출하지 않는다. 어드민 게시
# 검증이 슬롯 집합을 고정하므로 정상 세트에서는 늘 있다. 화 생성의 `episode_plan` 은 화 수·글자 수·소설 제목 여부를
# 싣는 유일한 자리라(지시문은 자리표시자를 못 쓴다), 이 슬롯이 없는 옛 문안으로 쓰면 출력이 구분자 형식을 따를 근거가 없다.
_REQUIRED_SLOTS: dict[str, frozenset[str]] = {
    "novelize_boundary": frozenset({_INSTRUCTION_SLOT, "max_turns", "turn_context"}),
    "novelize_chapter": frozenset({_INSTRUCTION_SLOT, "work_setting", "user_name", "episode_plan", "turn_context"}),
    "novelize_revise": frozenset({_INSTRUCTION_SLOT, "work_setting", "paragraphs", "target_range", "user_request"}),
}


@dataclass(frozen=True)
class NovelizePrompt:
    """`system_instruction` 은 `generate`/`generate_structured` 의 지시문 인자로, `prompt` 는 본문으로 보낸다."""

    system_instruction: str
    prompt: str


class NovelizeReviseResult(BaseModel):
    """문단 수정의 응답 스키마. 필드 설명은 모델에게 가는 스키마에 그대로 실린다."""

    paragraphs: list[str] = Field(
        description=(
            "[고칠 범위]의 문단들을 순서대로 대신할 문단 목록. 보통 [고칠 범위]의 문단 수와 같다. 범위 밖 문단은 넣지 "
            "않는다. 적어도 하나. 항목 하나가 문단 하나이고, 빈 줄과 [n] 번호를 넣지 않는다."
        )
    )


class NovelizeBoundaryResult(BaseModel):
    """장 경계 제안의 응답 스키마. 필드 설명은 모델에게 가는 스키마에 그대로 실린다."""

    end_turn: int = Field(
        description="다음 장이 끝나는 턴 번호. [원문 대화]의 [턴 n] 번호 중 하나이며 1 이상 [고를 수 있는 범위]의 끝 이하."
    )
    reason: str = Field(description="그 턴에서 장면이 매듭지어지는 이유. 이야기 속 사건으로 쓴 한 문장, 60자 이내.")


def _scope(is_story_chat: bool) -> str:
    return "story" if is_story_chat else "character"


def _require(channel: str, **values: str) -> None:
    empty = sorted(name for name, value in values.items() if not value.strip())
    if empty:
        raise PromptRenderError(f"channel={channel!r} 필수 값이 비었다: {empty}")


def _render(
    sections: Sequence[PromptSection],
    *,
    channel: str,
    is_story_chat: bool,
    values: dict[str, str],
    rating_sections: Sequence[PromptSection] | None,
) -> NovelizePrompt:
    """`rating_sections` 는 등급 규칙을 읽을 채팅 세트의 섹션이고, None 이면 등급 규칙을 붙이지 않는다."""
    scope = _scope(is_story_chat)
    present = {s.slot for s in select_sections_for_render(sections, channel=channel, scope=scope)}
    missing = sorted(_REQUIRED_SLOTS[channel] - present)
    if missing:
        raise PromptRenderError(f"channel={channel!r} scope={scope!r} 필수 슬롯이 없다: {missing}")

    channel_sections = [s for s in sections if s.channel == channel]
    instruction = render_prompt_channel(
        [s for s in channel_sections if s.slot == _INSTRUCTION_SLOT], channel=channel, scope=scope, values={}
    )
    prompt = render_prompt_channel(
        [s for s in channel_sections if s.slot != _INSTRUCTION_SLOT], channel=channel, scope=scope, values=values
    )
    if not instruction.strip() or not prompt.strip():
        raise PromptRenderError(f"channel={channel!r} scope={scope!r} 렌더 결과가 비었다")

    if rating_sections is None:
        return NovelizePrompt(system_instruction=instruction, prompt=prompt)
    rating = [
        s for s in select_sections_for_render(rating_sections, channel="system", scope=scope) if s.slot == "rule_rating"
    ]
    rating_text = render_prompt_channel(rating, channel="system", scope=scope, values={})
    if not rating_text.strip():
        raise PromptRenderError(f"channel='system' scope={scope!r} rule_rating 행이 없거나 비었다")
    return NovelizePrompt(system_instruction=f"{instruction}\n\n{rating_text}", prompt=prompt)


def _labels(chat_set: PromptSet, *, is_story_chat: bool) -> dict[str, str]:
    """원문 줄의 라벨과 같은 글자 — 요약 채널과 같은 고름(스토리 방은 진행자, 캐릭터 방은 캐릭터). 대화가 쓰던 라벨이라
    채팅 세트에서 읽는다(소설 레인 세트의 라벨 칸은 쓰지 않는다)."""
    assistant = chat_set.story_assistant_label if is_story_chat else chat_set.character_assistant_label
    return {"user_label": chat_set.user_label, "assistant_label": assistant}


def build_novelize_boundary_prompt(
    *,
    chat_set: PromptSet,
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    max_turns: int,
    user_name: str,
    turn_lines: str,
) -> NovelizePrompt:
    """묶음 경계 제안(구조화, 무과금). 지시문만 system 으로 보내고 등급 규칙은 붙이지 않는다 — 글을 쓰지 않고 끝 턴
    하나를 고르는 판정이다. `sections` 는 소설 레인 세트, `chat_set` 은 라벨을 읽을 채팅 세트다.

    `max_turns` 는 이번 후보 구간의 턴 수(상한과 남은 턴 수 중 작은 값, 1 이상). `user_name` 은 소설의 주인공 이름
    칸 값이고, 첫 장 이름을 받기 전이면 비어 그 섹션째 빠진다.

    `turn_lines` 는 후보 구간의 원문 줄이고 장 생성과 **같은 형식**이다(아래 `build_novelize_chapter_prompt` 참고).
    턴 번호 n 은 구간 안 상대 번호(1부터)라, 모델이 고른 번호를 호출부가 메시지 id 로 바꾼다."""
    if max_turns < 1:
        raise PromptRenderError(f"channel='novelize_boundary' max_turns={max_turns} — 고를 턴이 없다")
    _require("novelize_boundary", turn_lines=turn_lines)
    values = {
        **_labels(chat_set, is_story_chat=is_story_chat),
        "max_turns": str(max_turns),
        "user_name": user_name,
        "turn_lines": turn_lines,
    }
    return _render(
        sections, channel="novelize_boundary", is_story_chat=is_story_chat, values=values, rating_sections=None
    )


def build_novelize_chapter_prompt(
    *,
    chat_set: PromptSet,
    chat_sections: Sequence[PromptSection],
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    work_setting: str,
    user_name: str,
    setting_notes: str,
    previous_excerpt: str,
    turn_lines: str,
    character_notes: str = "",
    previous_summaries: str = "",
    episode_count: int = 1,
    episode_chars: int | None = None,
    novel_title_rule: str = "",
) -> NovelizePrompt:
    """묶음 생성·다시 만들기(자유 텍스트, 과금). `sections` 는 소설 레인 세트, `chat_set`·`chat_sections` 는 라벨과
    등급 규칙을 읽을 채팅 세트다. 지시문 뒤에 그 등급 규칙을 붙인다.

    값은 호출부가 만든다.
    - `work_setting`: 작품 설정 원문. 캐릭터 방은 `이름: {캐릭터명}` 한 줄 + 캐릭터 프롬프트, 스토리 방은 세계관
      설정 + 빈 줄 + 규칙(빈 값은 뺀다). 이미지 태그를 지운 뒤 작가 글의 `{{user}}` 를 소설 주인공 이름으로 바꾼다.
    - `user_name`: 소설의 주인공 이름 칸 값(필수 — 비면 호출하지 않는다).
    - `setting_notes`·`previous_excerpt`: 소설의 설정 노트, 직전 장 현재 본문의 끝 일부. 비면 섹션째 빠진다.
    - `turn_lines`: 구간 원문. 방 메시지를 `(created_at, id)` 순으로 읽고 모델 응답 하나를 한 턴으로 센다. 사용자
      메시지는 그 뒤 모델 응답과 같은 턴이고, 구간에 든 오프닝은 사용자 줄 없는 한 턴, 구간 끝의 응답 없는 사용자
      메시지는 넣지 않는다. 메시지마다 첫 줄 앞에 `"[턴 " + n + "] " + 라벨 + ": "` 를 붙이고 둘째 줄부터는 그대로
      둔다(같은 턴의 두 줄은 같은 n). 줄은 `"\\n"` 하나로 잇는다. 라벨은 이 함수가 `{user_label}`·`{assistant_label}`
      에 넣는 값과 같은 글자다. 본문은 이미지 태그를 지우고, 모델 응답 줄만 작가 글 이름 치환을 한다(사용자 줄은
      사용자가 친 글자 그대로). 장 경계 제안도 같은 형식을 쓴다 — 두 호출의 n 이 같은 턴을 가리키게.

      예: `[턴 1] 캐릭터: 왔어?` / `[턴 2] 사용자: 응, 늦어서 미안.` / `[턴 2] 캐릭터: 괜찮아.`
    - `character_notes`·`previous_summaries`: 메모를 적은 인물마다 한 줄, 앞 화 요약을 오래된 순으로 한 줄씩. 비면
      섹션째 빠진다.
    - `episode_count`·`episode_chars`·`novel_title_rule`: 이번 묶음을 나눌 화 수, 화 하나의 목표 글자 수, 소설 제목을
      쓸지 알리는 한 줄(화 수 지시 슬롯 `episode_plan` 에 들어간다).

    뒤의 다섯 값의 기본값은 첫 묶음이 아닌 한 화짜리 묶음이다. 글자 수를 비우면 설정의 화 목표 길이다."""
    _require("novelize_chapter", user_name=user_name, turn_lines=turn_lines)
    values = {
        **_labels(chat_set, is_story_chat=is_story_chat),
        "work_setting": work_setting,
        "user_name": user_name,
        "setting_notes": setting_notes,
        "previous_excerpt": previous_excerpt,
        "turn_lines": turn_lines,
        "character_notes": character_notes,
        "previous_summaries": previous_summaries,
        "episode_count": str(episode_count),
        "episode_chars": str(episode_chars if episode_chars is not None else settings.novelize_episode_target_chars),
        "novel_title_rule": novel_title_rule,
    }
    return _render(
        sections, channel="novelize_chapter", is_story_chat=is_story_chat, values=values, rating_sections=chat_sections
    )


def build_novelize_revise_prompt(
    *,
    chat_sections: Sequence[PromptSection],
    sections: Sequence[PromptSection],
    is_story_chat: bool,
    work_setting: str,
    setting_notes: str,
    paragraphs: Sequence[str],
    first_index: int,
    last_index: int,
    user_request: str,
) -> NovelizePrompt:
    """문단 수정(구조화, 과금). `sections` 는 소설 레인 세트이고, 지시문 뒤에 채팅 세트(`chat_sections`)의 등급 규칙을
    붙인다.

    `paragraphs` 는 장 현재 개정 본문을 빈 줄로 나눈 문단 목록이고 `first_index`·`last_index` 는 고칠 범위(0부터,
    양 끝 포함)다. 프롬프트에서는 문단마다 `[n] ` 을 붙여 빈 줄로 잇고 번호와 범위를 1부터 센다 — 사람이 읽는 번호라
    모델이 헷갈리지 않게. `work_setting`·`setting_notes` 는 장 생성과 같다."""
    _require("novelize_revise", user_request=user_request)
    if not 0 <= first_index <= last_index < len(paragraphs):
        raise PromptRenderError(
            f"channel='novelize_revise' 범위 {first_index}~{last_index} 가 문단 {len(paragraphs)}개 밖이다"
        )
    values = {
        "work_setting": work_setting,
        "setting_notes": setting_notes,
        "paragraph_lines": "\n\n".join(f"[{n}] {text}" for n, text in enumerate(paragraphs, start=1)),
        "first_paragraph": str(first_index + 1),
        "last_paragraph": str(last_index + 1),
        "user_request": user_request,
    }
    return _render(
        sections, channel="novelize_revise", is_story_chat=is_story_chat, values=values, rating_sections=chat_sections
    )
