"""사용자가 고르는 글쓰기 모델의 레지스트리 — 채팅 턴 생성과 소설 장 생성에 쓰인다.

id 는 공급사 모델명이 아닌 불투명 값(`gemini`·`sonnet`·`opus`)이다. 방·작업 행과 FE 가 이 값을 저장하고 주고받으므로,
모델 버전을 바꿀 때는 실제 모델 id 설정만 바꾸고 이 값은 그대로 둔다. 판정·요약·심사처럼 구조화 출력이 필요한 호출은
고른 모델과 무관하게 Gemini 다(`llm/routing.py`).

정적 데이터만 둔다 — 누가 어느 모델을 쓸 수 있는지는 기능별 허용 판정이 정한다. 가격의 소스는 `core/clover.py` 이고,
여기서는 호출할 때마다 그 모듈의 값을 읽는다(기본 인자나 사본으로 잡아 두면 `monkeypatch` 도 가격 변경도 따라오지
않는다). 채팅 코드(`api.chat`)를 import 하지 않는다 — `llm/client.py` 가 이 모듈을 import 하고 채팅 코드가 그 client 를
import 하므로, 여기서 `api.chat` 을 부르면 순환이다.
"""

from dataclasses import dataclass
from typing import Literal, assert_never

from api.core import clover
from api.core.config import settings

ChatModelId = Literal["gemini", "sonnet", "opus"]
# 이 모델의 생성 호출을 받는 구현. `llm/routing.py` 가 이 값으로 클라이언트를 고른다.
ChatModelProvider = Literal["gemini", "bedrock"]
DEFAULT_CHAT_MODEL: ChatModelId = "gemini"


@dataclass(frozen=True)
class ChatModelSpec:
    id: ChatModelId
    name: str
    provider: ChatModelProvider


# 순서가 곧 선택지의 순서다 — 기본 모델이 맨 앞.
CHAT_MODELS: tuple[ChatModelSpec, ...] = (
    ChatModelSpec(id="gemini", name="Gemini", provider="gemini"),
    ChatModelSpec(id="sonnet", name="Claude Sonnet 4.6", provider="bedrock"),
    ChatModelSpec(id="opus", name="Claude Opus 4.6", provider="bedrock"),
)
CHAT_MODELS_BY_ID: dict[ChatModelId, ChatModelSpec] = {m.id: m for m in CHAT_MODELS}


def parse_chat_model_id(raw: str) -> ChatModelId | None:
    """저장된 값이나 요청 값을 레지스트리 id 로 읽는다. 레지스트리 밖이면 None — DB 칸에 값 제약이 없어 레지스트리에서
    내린 모델의 옛 값이 남을 수 있고, 그 값을 어떻게 다룰지(거부·기본 모델로 대체)는 호출부가 정한다."""
    return raw if raw in CHAT_MODELS_BY_ID else None


def actual_model_id(model_id: ChatModelId) -> str:
    """공급사에 보내는 실제 모델 id. Gemini 는 채팅 생성 모델 설정이다 — 소설 장 생성은 Gemini 클라이언트가 소설화 모델
    설정으로 따로 고르므로 이 값과 다를 수 있다."""
    if model_id == "gemini":
        return settings.gemini_model_name
    if model_id == "sonnet":
        return settings.bedrock_sonnet_model_id
    if model_id == "opus":
        return settings.bedrock_opus_model_id
    assert_never(model_id)


def chat_turn_cost(model_id: ChatModelId) -> int:
    """채팅 턴 하나(새 턴·재생성·수정)의 클로버."""
    if model_id == "gemini":
        return clover.CHAT_TURN_COST
    if model_id == "sonnet":
        return clover.CHAT_TURN_COST_SONNET
    if model_id == "opus":
        return clover.CHAT_TURN_COST_OPUS
    assert_never(model_id)


def novel_chapter_cost(model_id: ChatModelId, *, regenerate: bool) -> int:
    """소설 장 생성·재생성 한 번의 클로버. Gemini 는 생성·재생성 상수를 따로 갖고(지금은 같은 값), 상위 모델은 같은
    호출이라 값 하나다."""
    if model_id == "gemini":
        return clover.NOVELIZE_CHAPTER_REGENERATE_COST if regenerate else clover.NOVELIZE_CHAPTER_GENERATE_COST
    if model_id == "sonnet":
        return clover.NOVELIZE_CHAPTER_COST_SONNET
    if model_id == "opus":
        return clover.NOVELIZE_CHAPTER_COST_OPUS
    assert_never(model_id)
