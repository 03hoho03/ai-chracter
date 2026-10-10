"""사용자가 고르는 글쓰기 모델의 레지스트리 — 채팅 턴 생성과 소설 장 생성에 쓰인다.

id 는 공급사 모델명이 아닌 불투명 값(`gemini`·`sonnet`·`opus`)이다. 방·작업 행과 FE 가 이 값을 저장하고 주고받으므로,
모델 버전을 바꿀 때는 실제 모델 id 설정만 바꾸고 이 값은 그대로 둔다. 판정·요약·심사처럼 구조화 출력이 필요한 호출은
고른 모델과 무관하게 구현을 고른다 — 판정·요약은 판정·요약 모델 설정으로, 나머지는 기본 모델로(`llm/routing.py`). 모델을 어느 구현이 어느 설정의 id 로 서비스하는지는
`llm/backends.py` 의 등록부가 정한다.

정적 데이터만 둔다 — 누가 어느 모델을 쓸 수 있는지는 기능별 허용 판정이 정한다. 가격의 소스는 `core/clover.py` 이고,
여기서는 호출할 때마다 그 모듈의 값을 읽는다(기본 인자나 사본으로 잡아 두면 `monkeypatch` 도 가격 변경도 따라오지
않는다). 채팅 코드(`api.chat`)를 import 하지 않는다 — `llm/client.py` 가 이 모듈을 import 하고 채팅 코드가 그 client 를
import 하므로, 여기서 `api.chat` 을 부르면 순환이다.
"""

from dataclasses import dataclass
from typing import Literal, TypeGuard, assert_never, get_args

from api.core import clover
from api.core.config import settings
from api.llm.backends import BACKENDS, MODEL_BACKENDS, call_site_model

# `as` 는 mypy strict 의 명시적 재export 요구 때문이다 — 기동 검증이 읽도록 정의를 잎 모듈(`llm/backends.py`)로 옮겼고,
# 이 이름을 여기서 가져오는 모듈이 많아 기존 import 경로를 그대로 쓰게 둔다.
from api.llm.backends import DEFAULT_CHAT_MODEL as DEFAULT_CHAT_MODEL
from api.llm.backends import ChatModelId as ChatModelId
from api.llm.backends import PromptSetModelId as PromptSetModelId
from api.llm.call_policy import BackendId, LLMCallSite


# 채팅방에 지정할 수 있는 모델. 아래 레지스트리의 `chat_selectable` 이 원천이고, 이 타입은 요청 검증용 사본이다 — 둘이
# 같은 집합인지는 테스트가 본다.
ChatRoomModelId = Literal["gemini", "opus"]

# 프롬프트 세트 체인의 모델 축(`prompt_sets.model`)이자 판정·요약 모델 설정의 값(정의는 `llm/backends.py`). 판정 전용 id 의
# 체인은 판정·요약 문안만 갖고, 그 id 로는 글을 쓰지 않으므로 글쓰기 모델 타입·레지스트리·파서·가격에는 넣지 않는다 — 넣으면
# 방·소설 요청이 그 값을 받는다. 그래서 이 타입은 프롬프트 세트를 다루는 곳(어드민 프롬프트 화면, 활성 세트 조회와 그 캐시)과
# 판정·요약 모델 설정에서만 쓴다. 글쓰기 모델 집합에 판정 전용 id 하나를 더한 집합인지는 테스트가 본다.
_PROMPT_SET_MODEL_IDS: frozenset[PromptSetModelId] = frozenset(get_args(PromptSetModelId))


@dataclass(frozen=True)
class ChatModelSpec:
    id: ChatModelId
    # 화면에 보이는 이름. 운영이 그 id 로 실제로 부르는 모델을 따른다 — 운영 경로나 모델 버전을 바꾸면 같이 고친다.
    name: str
    # 채팅방에서 고를 수 있는가. 거짓인 모델도 소설 장 생성·어드민·측정 리플레이에서는 그대로 쓴다.
    chat_selectable: bool
    # 화면이 베타 표시를 붙이는가.
    beta: bool

    @property
    def provider(self) -> BackendId:
        """이 모델의 기본 구현. 등록부의 기본 순서 표를 읽는다 — 사본을 두면 한쪽만 고쳐진다."""
        return MODEL_BACKENDS[self.id][0]


# 순서가 곧 선택지의 순서다 — 기본 모델이 맨 앞.
CHAT_MODELS: tuple[ChatModelSpec, ...] = (
    ChatModelSpec(id="gemini", name="Gemini", chat_selectable=True, beta=False),
    # 지금은 베타 표시가 보이는 곳이 채팅 모델 목록뿐이라 Sonnet 에서는 쓰이지 않는다. 나중에 채팅에 다시 열 때 표시 없이
    # 나가지 않게 미리 켜 둔다.
    ChatModelSpec(id="sonnet", name="Claude Sonnet 5.5", chat_selectable=False, beta=True),
    ChatModelSpec(id="opus", name="Claude Opus 5.5", chat_selectable=True, beta=True),
)
CHAT_MODELS_BY_ID: dict[ChatModelId, ChatModelSpec] = {m.id: m for m in CHAT_MODELS}


def is_chat_room_model(model: ChatModelId) -> TypeGuard[ChatRoomModelId]:
    """그 모델을 채팅방에서 고를 수 있는가."""
    return CHAT_MODELS_BY_ID[model].chat_selectable


def _default_chat_room_model() -> ChatRoomModelId:
    if not is_chat_room_model(DEFAULT_CHAT_MODEL):
        raise RuntimeError("기본 모델은 채팅방에서 고를 수 있어야 한다")
    return DEFAULT_CHAT_MODEL


# 기본 모델을 방 모델 타입으로 본 값. `DEFAULT_CHAT_MODEL` 은 등록부(`llm/backends.py`)에 전체 모델 타입으로 선언돼 있어
# 방 모델 자리(유효 방 모델·방 응답)에 그대로 넣을 수 없다. 기본 모델을 채팅에서 고를 수 없게 바꾸면 import 에서 멈춘다.
DEFAULT_CHAT_ROOM_MODEL: ChatRoomModelId = _default_chat_room_model()


def parse_chat_model_id(raw: str) -> ChatModelId | None:
    """저장된 값이나 요청 값을 레지스트리 id 로 읽는다. 레지스트리 밖이면 None — DB 칸에 값 제약이 없어 레지스트리에서
    내린 모델의 옛 값이 남을 수 있고, 그 값을 어떻게 다룰지(거부·기본 모델로 대체)는 호출부가 정한다."""
    return raw if raw in CHAT_MODELS_BY_ID else None


def parse_prompt_set_model_id(raw: str) -> PromptSetModelId | None:
    """저장된 세트의 모델 값을 체인 모델 축으로 읽는다. 판정 전용 id 도 받는다 — 어드민 버전 목록·조회·복원이 그 체인을
    다뤄야 해서다. 축 밖의 값이면 None."""
    return raw if raw in _PROMPT_SET_MODEL_IDS else None


def backend_model_id(backend: BackendId, model: PromptSetModelId) -> str:
    """그 구현이 그 모델로 보내는 실제 모델 id. Gemini 는 채팅 생성 모델 설정이다 — 판정·심사·소설화는 Gemini 클라이언트가
    호출마다 따로 모델을 고르므로 이 값과 다를 수 있다. 구현이 서비스하지 않는 모델이면 `KeyError` 다(호출부의 버그)."""
    value: str = getattr(settings, BACKENDS[backend].model_id_settings[model])
    return value


def configured_call_site_model(call_site: LLMCallSite) -> PromptSetModelId:
    """그 호출의 모델 — 판정·요약이면 지금 설정의 판정·요약 모델, 아니면 기본 모델(`llm/backends.py` 의 `call_site_model`).
    설정은 호출마다 읽는다(import 때 붙잡으면 테스트가 바꾼 설정이 실리지 않는다)."""
    return call_site_model(call_site, lambda name: str(getattr(settings, name)))


def chat_turn_cost(model_id: ChatModelId) -> int:
    """채팅 턴 하나(새 턴·재생성·수정)의 클로버."""
    if model_id == "gemini":
        return clover.CHAT_TURN_COST
    if model_id == "sonnet":
        return clover.CHAT_TURN_COST_SONNET
    if model_id == "opus":
        return clover.CHAT_TURN_COST_OPUS
    assert_never(model_id)


def novel_episode_unit_price(model_id: ChatModelId) -> int:
    """소설 화 하나의 클로버. 생성 한 번은 이 값 × 화 수를 낸다. 다시 만들기도 같은 호출이라 같은 값이다."""
    if model_id == "gemini":
        return clover.NOVELIZE_EPISODE_COST
    if model_id == "sonnet":
        return clover.NOVELIZE_EPISODE_COST_SONNET
    if model_id == "opus":
        return clover.NOVELIZE_EPISODE_COST_OPUS
    assert_never(model_id)
