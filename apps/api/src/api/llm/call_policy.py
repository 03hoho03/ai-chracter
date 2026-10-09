"""LLM 호출 위치(`LLMCallSite`)마다 어떤 정책으로 부르는지 적은 표. 판정 모델 스위치, 발행 심사, 소설화의 모델·실패 구분,
Gemini 요청 타임아웃, 상위 모델 선택 허용, Claude 의 타임아웃·출력 상한 프로필과 캐시 체크포인트를 한 행에서 정한다.
`llm/client.py`·`llm/routing.py`·`llm/bedrock.py` 의 call_site 집합과 판별 함수는 전부 이 표에서 나온다 — 새 call_site 는
여기 한 행을 더하면 이 세 파일의 갈래를 따라간다. 예외로 어드민 판정 비율의 분모(미리보기 생성인가 채팅 생성인가)는 이 표가
아니라 `admin/llm_usage.py` 가 call_site 이름의 `preview_` 접두로 따로 정하므로, 새 판정 call_site 는 이름도 그 규칙에 맞춘다.

표에는 설정 값이 아니라 설정 **이름**(또는 설정이 아닌 고정값)만 담는다. 값은 쓰는 쪽이 호출마다 `settings` 에서 읽는다 —
import 때 값을 붙잡으면 테스트가 바꾼 설정이 호출에 실리지 않는다. 이와 별개로, 이름만 담으니 이 모듈은 `settings` 를 비롯한
다른 `api` 모듈을 import 할 필요가 없어 잎 모듈로 둔다. 그래서 `llm/client.py`·`llm/routing.py`·`llm/bedrock.py` 가 이 모듈을
import 해 집합을 만들어도 순환을 따질 일이 없다.
"""

from dataclasses import dataclass
from typing import Literal

# `gemini_usage`·`bedrock_usage` 로그의 grep 키다. 호출부와 1:1이라
# 값을 바꾸거나 합치면 로그 분포가 끊긴다. 재생성은 `chat_generate`로 함께 집계한다.
LLMCallSite = Literal[
    "chat_generate",
    "chat_stat_judgment",
    "chat_ending_judgment",
    "chat_situational_image",
    # 스토리 미디어 북 칸 판정. 재생성도 여기로 함께 집계한다(생성과 같은 규칙).
    "chat_media_book_image",
    "chat_memory_summary",
    "preview_generate",
    "preview_stat_judgment",
    "preview_ending_judgment",
    "preview_media_book_image",
    "publish_filter_character",
    "publish_filter_story",
    "seed_story_generate",
    "seed_similarity_review",
    # 소설화: 장 생성(스트리밍, 재생성도 여기로 함께 집계한다), AI 문단 수정(구조화), 장 경계 제안(구조화).
    "novelize_chapter",
    "novelize_revise",
    "novelize_boundary",
    # 노벨 공개 전 텍스트 심사(구조화). 발행 심사처럼 실패하면 공개하지 않는(fail-closed) 심사라 발행 심사와 같은 모델·
    # 타임아웃 스위치를 따른다(아래 표의 `publish_filter`) — 심사 모델을 바꿀 때 두 심사가 함께 움직인다.
    "novel_publish_screen",
    # 지난 턴을 같은 입력으로 다시 생성해 비교하는 측정 도구의 생성 호출. 사용량이 실제 대화(`chat_generate`)와 섞이지
    # 않게 따로 집계하고, Claude 로 쓴 턴도 다시 생성할 수 있게 모델 선택을 허용한다(아래 표의 `model_selectable`). 설정은
    # 채팅 생성과 같아 타임아웃·출력 상한·사고 설정이 같다. 판정·심사에는 넣지 않는다.
    "replay_generate",
]

JudgmentKind = Literal["stat", "ending", "image"]

# `core/config.py` 의 Gemini 요청 타임아웃 설정 이름. 값은 `request_timeout_ms` 가 호출마다 읽는다.
GeminiTimeoutSetting = Literal[
    "gemini_generate_timeout_ms",
    "gemini_judgment_timeout_ms",
    "gemini_memory_summary_timeout_ms",
    "gemini_publish_filter_timeout_ms",
    "gemini_novelize_chapter_timeout_ms",
    "gemini_novelize_revise_timeout_ms",
    "gemini_novelize_boundary_timeout_ms",
]

# 시드 스크립트 호출은 작품 하나를 통째로 만드는 비스트리밍 호출이라 운영 호출 상한(최대 60초)에 걸릴 수 있다. 운영
# 서버가 부르는 호출이 아니어서 `.env` 로 바꿀 일이 없으므로 설정 키가 아니라 여기 고정한다.
_SEED_TIMEOUT_MS = 300_000


@dataclass(frozen=True, kw_only=True)
class CallPolicy:
    # Gemini 요청에 실을 타임아웃 — 설정 이름, 또는 설정이 아닌 고정 ms. 기본값이 없는 것은 일부러다: 요청 단위 값 없이
    # 나간 호출이 한 번이라도 있으면 SDK 가 클라이언트 헤더에 전역값의 서버 기한 헤더를 써 넣어, 뒤따르는 호출이 자기
    # 값을 헤더에 싣지 못한다. 새 call_site 가 타임아웃을 정하지 않고 생기지 않게 한다.
    gemini_timeout: GeminiTimeoutSetting | int
    # 사용자가 고른 모델(상위 모델이면 Bedrock)을 따르는 호출인가. 아니면 상위 모델이 실려 와도 경고 후 Gemini 로 간다.
    model_selectable: bool = False
    # 판정 종류. 구조화 호출의 모델을 `gemini_<종류>_judgment_model_name` 스위치로 고르고, 어드민 판정 비율의 대상이 된다.
    # 판정을 종류별로 나누는 건 모델을 바꿨을 때 품질이 종류마다 따로 움직여서다 — 같은 비교에서 스탯·엔딩은 현행과
    # 맞았지만 그림 매칭은 어긋나, 셋을 한 스위치로 묶으면 옮길 수 있는 둘까지 묶인다. 기억 요약은 매 턴 생성 프롬프트에
    # 실려 생성 품질에 바로 닿고, 시드 스크립트 호출은 운영 판정이 아니라서 판정에 넣지 않는다.
    # `judgment_kind`·`publish_filter`·`novelize == "prose"` 는 서로 배타다 — 한 행에 둘을 켜면 모델 고르기에서 조용히
    # 앞의 것(판정 → 발행 심사 → 소설화 순)이 이긴다.
    judgment_kind: JudgmentKind | None = None
    # 발행 심사. 실패하면 발행이 막히는(fail-closed) 경로라 판정과 따로 모델을 바꾸고 되돌릴 수 있게 둔다.
    publish_filter: bool = False
    # 소설화 호출이면 그 갈래. 결과를 소설 본문으로 저장하므로, 채팅이라면 경고만 남기고 넘길 결과(출력 상한에서 잘림·빈
    # 본문)를 구분된 실패(`LLMTruncatedError`·`LLMEmptyResponseError`)로 올린다. `prose` 는 본문을 쓰는 장 생성·문단
    # 수정으로 소설화 모델·출력 상한·사고 설정(`gemini_novelize_*`)을 쓴다. `boundary`(장 경계 제안)는 턴 번호 몇 개를
    # 고르는 판정이라 실패 구분만 받고 모델·상한·사고는 기본을 따른다.
    novelize: Literal["prose", "boundary"] | None = None
    # Claude 의 타임아웃·출력 상한 프로필. `chapter` 는 소설 장 생성용 긴 상한(`bedrock_chapter_*`), `chat` 은 채팅 상한
    # (`bedrock_chat_*`). 소설화 갈래에서 파생하지 않는 것은 Claude 로 가는 소설화 호출이 지금 장 생성 하나뿐이어서다 —
    # 문단 수정·장 경계 제안은 구조화 호출이고 모델 선택 대상이 아니라 언제나 Gemini 로 가므로 이 값이 운영에서 쓰이지
    # 않는다. 이들을 Claude 로 보내게 되면 그때 상한을 따로 정해야 하므로 갈래와 묶지 않고 행마다 적는다.
    claude_limits: Literal["chat", "chapter"] = "chat"
    # Claude 에 빌더가 나눈 프롬프트 블록을 캐시 체크포인트와 함께 보내는가(채팅 턴 생성과 그 측정용 다시 생성).
    claude_cache_checkpoint: bool = False


CALL_POLICIES: dict[LLMCallSite, CallPolicy] = {
    "chat_generate": CallPolicy(
        gemini_timeout="gemini_generate_timeout_ms", model_selectable=True, claude_cache_checkpoint=True
    ),
    "chat_stat_judgment": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="stat"),
    "chat_ending_judgment": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="ending"),
    "chat_situational_image": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="image"),
    "chat_media_book_image": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="image"),
    "chat_memory_summary": CallPolicy(gemini_timeout="gemini_memory_summary_timeout_ms"),
    "preview_generate": CallPolicy(gemini_timeout="gemini_generate_timeout_ms"),
    "preview_stat_judgment": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="stat"),
    "preview_ending_judgment": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="ending"),
    "preview_media_book_image": CallPolicy(gemini_timeout="gemini_judgment_timeout_ms", judgment_kind="image"),
    "publish_filter_character": CallPolicy(gemini_timeout="gemini_publish_filter_timeout_ms", publish_filter=True),
    "publish_filter_story": CallPolicy(gemini_timeout="gemini_publish_filter_timeout_ms", publish_filter=True),
    "seed_story_generate": CallPolicy(gemini_timeout=_SEED_TIMEOUT_MS),
    "seed_similarity_review": CallPolicy(gemini_timeout=_SEED_TIMEOUT_MS),
    "novelize_chapter": CallPolicy(
        gemini_timeout="gemini_novelize_chapter_timeout_ms",
        model_selectable=True,
        novelize="prose",
        claude_limits="chapter",
    ),
    "novelize_revise": CallPolicy(gemini_timeout="gemini_novelize_revise_timeout_ms", novelize="prose"),
    "novelize_boundary": CallPolicy(gemini_timeout="gemini_novelize_boundary_timeout_ms", novelize="boundary"),
    "novel_publish_screen": CallPolicy(gemini_timeout="gemini_publish_filter_timeout_ms", publish_filter=True),
    "replay_generate": CallPolicy(
        gemini_timeout="gemini_generate_timeout_ms", model_selectable=True, claude_cache_checkpoint=True
    ),
}
