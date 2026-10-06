"""생성 한 번(묶음)을 몇 화로 나눌지와, 모델마다 다른 묶음 상한. DB 를 타지 않는다.

화 수는 서버가 원문 분량으로 정한다 — 사용자가 확인하는 금액이 화 수 × 화 단가라, 같은 구간이면 확인 화면과 작업
생성이 같은 값을 내야 한다. 그래서 계산은 이 모듈의 순수 함수 하나이고 설정은 부를 때마다 읽는다.

묶음 상한(턴 수·화 수)이 모델마다 다른 것은 모델마다 출력 속도와 출력 상한이 달라서다. 원문은 빠짐없이 옮기므로
묶음의 출력 길이는 턴 수가 정하고, 화 수 상한은 그 출력을 몇 덩어리로 나눌 수 있는지를 정한다."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, assert_never

from api.chat.prompt_builder import PromptNames, _turn_text
from api.core.config import settings
from api.llm.chat_models import ChatModelId
from api.novelize.source import SourceTurn


def k_max(model: ChatModelId) -> int:
    """묶음 하나가 나뉠 수 있는 화 수의 상한."""
    if model == "gemini":
        return settings.novelize_k_max_gemini
    if model == "sonnet":
        return settings.novelize_k_max_sonnet
    if model == "opus":
        return settings.novelize_k_max_opus
    assert_never(model)


def chapter_max_turns(model: ChatModelId) -> int:
    """묶음 하나가 담을 수 있는 원문 턴(AI 응답) 수의 상한."""
    if model == "gemini":
        return settings.novelize_chapter_max_turns
    if model == "sonnet":
        return settings.novelize_chapter_max_turns_sonnet
    if model == "opus":
        return settings.novelize_chapter_max_turns_opus
    assert_never(model)


def source_chars(turns: Sequence[SourceTurn], names: PromptNames) -> int:
    """구간 원문의 글자 수 — 모델이 실제로 받는 글자로 센다. 메시지마다 이미지 태그를 지우고 모델 응답의 작가 글 이름을
    바꾼 뒤(원문 줄과 같은 처리) 앞뒤 공백을 뺀 길이를 더한다. 턴 표시·라벨은 세지 않는다 — 본문으로 옮겨지는 글이
    아니다."""
    return sum(
        len(_turn_text(message, names, strip_tags=True).strip())
        for turn in turns
        for message in (*turn.users, turn.assistant)
    )


def episode_count(chars: int, model: ChatModelId) -> int:
    """원문 `chars` 글자를 몇 화로 나눌지. 원문 글자 × 비율 ÷ 화 목표 길이를 반올림(0.5 는 올림)하고 1 과 그 모델의 화
    수 상한 사이로 자른다. 소수 계산은 `Decimal` 로 한다 — 이진 부동소수는 정확히 0.5 인 경계를 아래로 놓칠 수 있다
    (비율 0.7·목표 4,500자에서 22,500자는 3.5 인데 부동소수로는 3.4999… 라 3 이 된다). 비율은 설정에 적힌 십진 표기
    그대로 읽는다."""
    raw = Decimal(chars) * Decimal(str(settings.novelize_source_ratio)) / Decimal(settings.novelize_episode_target_chars)
    rounded = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return max(1, min(k_max(model), rounded))


RegenerateIneligibility = Literal["too_many_episodes", "too_many_turns"]


def regenerate_ineligibility(
    model: ChatModelId, *, episode_count: int, turn_count: int
) -> RegenerateIneligibility | None:
    """이 모델로 묶음을 다시 만들 수 없는 이유, 할 수 있으면 None. 다시 만들기는 지금 화 수를 그대로 지키므로(화 행과
    그에 딸린 읽은 위치·작가의 말·개정 이력을 살리려는 것), 그 화 수가 모델의 화 수 상한을 넘거나 묶음의 턴 수가 모델의
    턴 상한을 넘으면 그 모델의 작업 상한 근거가 깨진다 — 짧게 쓰도록 정한 모델에게 긴 묶음을 맡기게 된다."""
    if episode_count > k_max(model):
        return "too_many_episodes"
    if turn_count > chapter_max_turns(model):
        return "too_many_turns"
    return None
