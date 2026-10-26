"""측정 서버의 소설 프롬프트 덤프 — 소설 작업이 모델을 부르기 직전에 그 호출을 다시 렌더할 입력을 JSONL 한 줄로 남긴다.

채팅 덤프(`chat/prompt_dump.py`·`chat/turn_engine.py`)와 파일·코드를 나눈다. 채팅 리플레이가 읽는 파일에 소설 줄이 섞이지 않고,
소설 쪽을 고쳐도 채팅 측정 경로에 닿지 않게 하려는 것이다.

줄에는 렌더된 지시문·본문 대신 그 sha256 을 남기고, 렌더러(`prompts._render`)가 받은 입력을 남긴다: 섹션을 읽은 소설 세트 id,
채널, 원작 종류(`scope`), 등급 규칙을 붙였는가, 슬롯 값 사전. 렌더러는 이 입력만 읽는 순수 함수이고 게시된 세트의 섹션은 고치지
않으므로, 세트 id 의 섹션과 슬롯 값으로 다시 렌더하면 같은 바이트가 나온다 — sha 로 그것을 확인한다. 원문 줄의 화자 라벨과 화 목표
글자 수처럼 설정·다른 세트에서 온 값은 이미 슬롯 값 안에 들어 있다."""

import hashlib
import json
import logging
import uuid

from api.core.config import settings
from api.llm.client import LLMCallContext, structured_model
from api.llm.routing import resolve_backend
from api.novelize.job_variants import JobVariant
from api.novelize.prompts import NovelizePrompt

logger = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump_novel_prompt(
    *,
    job_id: uuid.UUID,
    job_model: str | None,
    variant: JobVariant,
    usage: LLMCallContext,
    prompt: NovelizePrompt,
    schema: str | None,
) -> None:
    """덤프 경로가 없으면(운영) 아무것도 하지 않는다 — 파일을 열지 않고 모델 해석도 하지 않는다. 부르는 쪽은 모델 호출 **앞**에서
    부른다 — 실패한 호출의 입력도 남아야 다시 보내 볼 수 있다.

    칸: 작업 id, 갈래, 호출 위치, 작업에 적힌 모델(`jobModel`, 모델 칸이 생기기 전 작업은 null), 실제로 보낸 모델 id(`callModel`,
    라우터와 같은 해석 — Gemini 는 클라이언트가 소설화 모델 설정으로 고르는 id), 소설 세트 id, 채널, 원작 종류, 등급 규칙 여부,
    슬롯 값 사전, 지시문·본문 sha256, 응답 스키마 이름(자유 텍스트 생성은 null). 세트의 판 번호는 싣지 않는다 — 서빙 경로는 판 표를
    읽지 않으므로(`tests/test_prompt_semver_boundary.py`), 판은 세트 id 로 판 표와 이어 읽는다(턴 기록의 단계별 배정 칸과 같다).

    쓰기 실패는 경고만 남기고 삼킨다 — 덤프는 측정용 부가 기록이라 작업 결과를 바꾸면 안 된다. 경고에는 작업 id 와 호출 위치만
    싣는다(슬롯 값에 원문이 들어 있다). 작업 실행 프로세스가 둘(api·소설화 워커)이어도 줄이 섞이지 않게 한 줄을 한 번의 `write`
    로 추가한다(채팅 덤프와 같다)."""
    path = settings.novel_prompt_dump_path
    if path is None:
        return
    try:
        backend, sent = resolve_backend(usage.call_site, usage.model, usage.call_model)
        record = {
            "jobId": str(job_id),
            "branch": variant,
            "callSite": usage.call_site,
            "jobModel": job_model,
            "callModel": structured_model(usage.call_site, sent) if backend == "gemini" else sent,
            "novelSetId": str(prompt.prompt_set_id) if prompt.prompt_set_id is not None else None,
            "channel": prompt.channel,
            "scope": prompt.scope,
            "withRating": prompt.with_rating,
            "values": prompt.values,
            "systemSha256": _sha256(prompt.system_instruction),
            "promptSha256": _sha256(prompt.prompt),
            "schema": schema,
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("소설 프롬프트 덤프 실패 (job=%s, call_site=%s)", job_id, usage.call_site, exc_info=True)
