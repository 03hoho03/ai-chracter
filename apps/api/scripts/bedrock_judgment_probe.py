"""Bedrock 의 Claude 로 판정 하나를 실제로 보내 보는 확인용 스크립트(일회성, 유료 호출).

판정 모델을 Claude 로 바꾸기 전에, 이 계정의 Bedrock 이 판정 경로(구조화 출력 `output_config.format`, 사고 끔)를 모델마다
받는지와 첫 호출의 지연(새 스키마의 첫 컴파일 포함)을 본다. 고정 합성 판정 하나를 모델마다 한 번 보낸다 — 사용자 대화가
아니다. 호출은 앱의 Bedrock 구현(`BedrockLLMClient.generate_structured`)을 그대로 거치므로 요청 모양·타임아웃·실패 정규화가
운영 판정과 같다. 사용량은 Redis 에 쓰지 않고 이 스크립트가 받아 출력한다.

자격은 이 명령의 프로세스 환경변수로만 받는다 — `BEDROCK_ACCESS_KEY_ID`·`BEDROCK_SECRET_ACCESS_KEY`·`BEDROCK_REGION` 셋이
환경변수에 없으면 돌지 않는다(앱 설정이 `.env` 에서 읽은 값으로 대신하지 않는다). 자격 값은 출력하지 않는다. `--yes` 가 없으면
비용 추정만 출력하고 호출하지 않는다.

    cd apps/api && BEDROCK_ACCESS_KEY_ID=… BEDROCK_SECRET_ACCESS_KEY=… BEDROCK_REGION=ap-northeast-2 \\
        uv run python scripts/bedrock_judgment_probe.py --yes

`--models haiku` 처럼 일부만 고를 수 있다(기본 haiku,sonnet,opus — 각 1회). `--timeout-ms` 기본값은 운영 판정 타임아웃(20초)이다.
AWS 의 Bedrock 구조화 출력 안내는 새 스키마의 첫 컴파일이 몇 분까지 걸릴 수 있고, 컴파일한 문법을 첫 접근부터 24시간 동안
같은 계정의 같은 스키마에 다시 쓴다고 적는다. 그래서 첫 컴파일 시간을 재려면 타임아웃을 넉넉히 늘려 돌린다.

    ... uv run python scripts/bedrock_judgment_probe.py --yes --timeout-ms 300000

기본값(20초)으로 돌려 시간 초과로 끝나면 그것 자체가 확인할 사실이다(판정 모델을 바꾸기 전에 워밍 호출이 필요하다는 뜻).
첫 호출 뒤 같은 모델을 다시 돌려 두 번째 지연이 첫 호출보다 얼마나 짧은지 본다 — 캐시가 실제로 듣는지는 이 차이로 확인한다.

첫 호출이 `AccessDeniedException` 으로 끝나면 IAM 정책에 그 모델의 추론 프로필·foundation-model ARN 이 있는지, 그리고 마켓플레이스
동의가 필요한 모델인지 본다 — 동의는 콘솔(관리자 권한)에서 수락하고, 앱 IAM 사용자에게 마켓플레이스 권한을 주지 않는다.
"""

import argparse
import asyncio
import os
import sys
import time
from typing import Any, cast, get_args

from api.chat.prompt_builder import StatRuleJudgmentResult
from api.core.config import settings
from api.llm import bedrock as bedrock_module
from api.llm.backends import PromptSetModelId
from api.llm.bedrock import BedrockLLMClient
from api.llm.chat_models import backend_model_id
from api.llm.client import LLMCallContext, LLMCallSite, LLMClientError, request_timeout_ms
from api.llm.pricing import estimate_cost_usd

_CREDENTIAL_ENV = ("BEDROCK_ACCESS_KEY_ID", "BEDROCK_SECRET_ACCESS_KEY", "BEDROCK_REGION")
_CALL_SITE: LLMCallSite = "chat_stat_judgment"
# 추정에 쓰는 토큰 수 — 아래 프롬프트에 구조화 출력이 붙이는 시스템 토큰 여유를 더한 넉넉한 값.
_ESTIMATED_INPUT_TOKENS = 2_000
_ESTIMATED_OUTPUT_TOKENS = 50

# 고정 합성 판정. 규칙 r2 만 이번 턴에 일어난 일에 맞는다.
_PROMPT = """너는 대화형 이야기의 스탯 규칙 판정기다. 아래 규칙 가운데 이번 턴에 실제로 일어난 일에 해당하는 규칙의 id 만 고른다.
해당하는 규칙이 없으면 빈 목록이다.

[규칙]
- r1: 주인공이 상대에게 거짓말을 한다.
- r2: 주인공이 상대에게 우산을 건넨다.
- r3: 두 사람이 다툰다.

[이번 턴]
나: 비가 많이 오네요. 이 우산 쓰세요, 저는 금방 뛰어가면 돼요.
너: (잠시 망설이다 우산을 받아 든다) 고마워요. 다음에 꼭 돌려줄게요.
"""


def _prepare(model: PromptSetModelId, timeout_ms: int) -> None:
    """앱 설정을 이 스크립트의 실행 조건으로 맞춘다 — 자격은 프로세스 환경변수의 값, 판정 모델은 이번에 볼 모델."""
    settings.bedrock_access_key_id = os.environ["BEDROCK_ACCESS_KEY_ID"]
    settings.bedrock_secret_access_key = os.environ["BEDROCK_SECRET_ACCESS_KEY"]
    settings.bedrock_region = os.environ["BEDROCK_REGION"]
    settings.stat_judgment_model = model
    settings.gemini_judgment_timeout_ms = timeout_ms


async def _probe(model: PromptSetModelId, timeout_ms: int) -> dict[str, Any]:
    _prepare(model, timeout_ms)
    sent = backend_model_id("bedrock", model)
    seen: dict[str, Any] = {}

    async def capture_usage(call_site: str, model_id: str, usage_metadata: object | None) -> None:
        seen["usage"] = usage_metadata

    # 구현 모듈의 이름을 바꿔 끼운다(리플레이의 사용량 잡기와 같은 방식) — 구현이 그 이름으로 부르기 때문이다.
    real_parse = getattr(bedrock_module, "parse_structured")  # noqa: B009

    def capture_parse(message: Any, schema: Any, provider: Any, label: str) -> Any:
        seen["stop_reason"] = message.stop_reason
        return real_parse(message, schema, provider, label)

    setattr(bedrock_module, "record_usage", capture_usage)  # noqa: B010
    setattr(bedrock_module, "parse_structured", capture_parse)  # noqa: B010
    started = time.monotonic()
    try:
        result = await BedrockLLMClient().generate_structured(
            _PROMPT, StatRuleJudgmentResult, usage=LLMCallContext(_CALL_SITE, None, None)
        )
        outcome: dict[str, Any] = {"parsed": result.model_dump()}
    except LLMClientError as exc:
        cause = exc.__cause__
        outcome = {"error": f"{type(exc).__name__}: {exc}", "cause": type(cause).__name__ if cause else None}
    finally:
        setattr(bedrock_module, "parse_structured", real_parse)  # noqa: B010
    outcome["seconds"] = round(time.monotonic() - started, 2)
    usage = seen.get("usage")
    cost = None
    if usage is not None:
        cost = estimate_cost_usd(
            sent,
            input_tokens=usage.prompt_token_count,
            cached_tokens=usage.cached_content_token_count,
            cache_write_tokens=usage.cache_write_token_count,
            output_tokens=usage.candidates_token_count,
            thoughts_tokens=usage.thoughts_token_count,
        )
    return {
        "model": model,
        "modelId": sent,
        "stopReason": seen.get("stop_reason"),
        "promptTokens": getattr(usage, "prompt_token_count", None),
        "outputTokens": getattr(usage, "candidates_token_count", None),
        "costUsd": cost,
        **outcome,
    }


def _estimate(models: list[PromptSetModelId]) -> float:
    total = 0.0
    for model in models:
        cost = estimate_cost_usd(
            backend_model_id("bedrock", model),
            input_tokens=_ESTIMATED_INPUT_TOKENS,
            cached_tokens=0,
            output_tokens=_ESTIMATED_OUTPUT_TOKENS,
            thoughts_tokens=0,
        )
        assert cost is not None, model
        print(f"  {model}: 약 ${cost:.4f} (입력 {_ESTIMATED_INPUT_TOKENS} · 출력 {_ESTIMATED_OUTPUT_TOKENS} 토큰 가정)")
        total += cost
    return total


def _models(raw: str) -> list[PromptSetModelId]:
    allowed = [m for m in get_args(PromptSetModelId) if m != "gemini"]
    models = [m.strip() for m in raw.split(",") if m.strip()]
    unknown = [m for m in models if m not in allowed]
    if unknown or not models:
        raise argparse.ArgumentTypeError(f"모델은 {', '.join(allowed)} 중에서 고른다: {raw!r}")
    # 적은 순서대로 부른다(기본은 가장 싼 haiku 부터).
    return cast(list[PromptSetModelId], models)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", type=_models, default=_models("haiku,sonnet,opus"))
    parser.add_argument("--timeout-ms", type=int, default=request_timeout_ms(_CALL_SITE))
    parser.add_argument("--yes", action="store_true", help="유료 호출을 실제로 보낸다(없으면 추정만 출력)")
    args = parser.parse_args()

    print(f"대상: {', '.join(args.models)} 각 1회, Bedrock, 판정 타임아웃 {args.timeout_ms}ms")
    print(f"예상 비용 합계: 약 ${_estimate(args.models):.4f}")
    if not args.yes:
        print("--yes 가 없어 호출하지 않는다.")
        return 2
    missing = [name for name in _CREDENTIAL_ENV if not os.environ.get(name, "").strip()]
    if missing:
        print(f"프로세스 환경변수에 {', '.join(missing)} 가 없어 호출하지 않는다.", file=sys.stderr)
        return 2

    failed = False
    for model in args.models:
        row = asyncio.run(_probe(model, args.timeout_ms))
        failed = failed or "error" in row
        print(row)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
