"""기동 검증(`assignment_errors`)이 내는 문장을 글자 그대로 고정한다.

기동 검증의 다른 테스트는 문장 일부(`match=`)만 보므로, 검사를 함수로 떼거나 옮길 때 구분 기호·괄호 한 글자가 바뀌어도
초록으로 남는다. 운영자가 기동 실패 로그에서 읽는 문장이라 바이트가 바뀌면 안 된다. 설정은 env 가 아니라 아래 사전에서
읽는다 — 로컬 `.env` 와 CI 의 기본값이 달라도 같은 문장이 나온다."""

import dataclasses
from collections.abc import Callable, Mapping

import pytest

from api.llm import backends
from api.llm.backends import assignment_errors
from api.llm.call_policy import BackendId, LLMCallSite

_BASE_SETTINGS: dict[str, str] = {
    "stat_judgment_model": "gemini",
    "ending_judgment_model": "gemini",
    "image_judgment_model": "gemini",
    "memory_summary_model": "gemini",
    "memory_episode_model": "gemini",
    "memory_fact_model": "gemini",
    "gemini_model_name": "gemini-test-flash",
    "bedrock_access_key_id": "",
    "bedrock_secret_access_key": "",
    "bedrock_region": "",
    "bedrock_sonnet_model_id": "bedrock-sonnet-test",
    "bedrock_opus_model_id": "bedrock-opus-test",
    "bedrock_haiku_model_id": "bedrock-haiku-test",
    "anthropic_direct_api_key": "",
    "anthropic_sonnet_model_id": "claude-sonnet-test",
    "anthropic_opus_model_id": "claude-opus-test",
    "anthropic_haiku_model_id": "claude-haiku-4-5",
    "anthropic_structured_effort": "high",
}


def _reader(**overrides: str) -> Callable[[str], str]:
    values = {**_BASE_SETTINGS, **overrides}

    def read(name: str) -> str:
        return values[name]

    return read


_STAT_ON_ANTHROPIC: Mapping[LLMCallSite, BackendId] = {
    "chat_stat_judgment": "anthropic",
    "preview_stat_judgment": "anthropic",
}

_EFFORT_TAIL = "(사고를 끈 요청은 low·medium·high 만 받는다)"


def test_startup_assignment_errors_keep_their_exact_sentences_for_an_effort_above_the_ceiling() -> None:
    read = _reader(
        stat_judgment_model="haiku",
        anthropic_direct_api_key="sk-test",
        anthropic_haiku_model_id="claude-haiku-5-5",
        anthropic_structured_effort="xhigh",
    )

    assert assignment_errors(_STAT_ON_ANTHROPIC, read) == [
        f"stat_judgment_model 가 haiku 인 {call_site} — claude-haiku-5-5 는 사고를 끄고 판정하는데 "
        f"ANTHROPIC_STRUCTURED_EFFORT=xhigh 다{_EFFORT_TAIL}"
        for call_site in (
            "chat_stat_judgment",
            "chat_scene_judgment",
            "preview_stat_judgment",
            "preview_scene_judgment",
        )
    ]


def test_startup_assignment_errors_report_missing_credentials_and_the_effort_ceiling_for_the_same_call() -> None:
    """자격이 빈 오류 뒤에도 같은 호출의 깊이 검사가 이어진다 — 둘 중 하나만 보이면 운영자가 고친 뒤 다시 막힌다."""
    read = _reader(
        stat_judgment_model="haiku", anthropic_haiku_model_id="claude-haiku-5-5", anthropic_structured_effort="max"
    )

    expected: list[str] = []
    for call_site in ("chat_stat_judgment", "chat_scene_judgment", "preview_stat_judgment", "preview_scene_judgment"):
        entry = f"stat_judgment_model 가 haiku 인 {call_site}"
        expected.append(f"{entry} — 가는 구현 anthropic 의 ANTHROPIC_DIRECT_API_KEY 가 비어 있다")
        expected.append(
            f"{entry} — claude-haiku-5-5 는 사고를 끄고 판정하는데 ANTHROPIC_STRUCTURED_EFFORT=max 다{_EFFORT_TAIL}"
        )
    assert assignment_errors(_STAT_ON_ANTHROPIC, read) == expected


def test_startup_assignment_errors_keep_their_exact_sentence_for_a_backend_that_serves_none_of_the_models() -> None:
    assert assignment_errors({"chat_stat_judgment": "anthropic"}, _reader()) == [
        "LLM_CALL_SITE_BACKENDS 의 chat_stat_judgment:anthropic — anthropic 는 이 호출의 모델(gemini)을 하나도 서비스하지 않는다"
    ]


def test_startup_assignment_errors_keep_their_exact_sentence_for_a_moved_route_without_credentials() -> None:
    assert assignment_errors({"chat_generate": "anthropic"}, _reader()) == [
        "LLM_CALL_SITE_BACKENDS 의 chat_generate:anthropic — 경로를 anthropic 로 옮기는데 ANTHROPIC_DIRECT_API_KEY 가 비어 있다"
    ]


def test_startup_assignment_errors_keep_their_exact_sentence_for_a_judgment_whose_backend_lacks_its_call_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """지금 등록부의 구현은 모두 구조화 호출을 받아 이 문장이 나오지 않는다. 구조화를 받지 못하는 구현을 등록부에 끼워 문장을 꺼낸다."""
    no_structured = dataclasses.replace(
        backends.BACKENDS["anthropic"].capabilities, structured="none", structured_images=False
    )
    monkeypatch.setitem(
        backends.BACKENDS,
        "anthropic",
        dataclasses.replace(backends.BACKENDS["anthropic"], capabilities=no_structured),
    )
    read = _reader(stat_judgment_model="haiku", anthropic_direct_api_key="sk-test")

    assert assignment_errors(_STAT_ON_ANTHROPIC, read) == [
        f"stat_judgment_model 가 haiku 인 {call_site} — 가는 구현 anthropic 는 이 호출의 방식(structured)을 받지 못한다"
        for call_site in (
            "chat_stat_judgment",
            "chat_scene_judgment",
            "preview_stat_judgment",
            "preview_scene_judgment",
        )
    ]


def test_startup_assignment_errors_are_empty_for_a_haiku_4_judgment_whatever_the_effort() -> None:
    """Haiku 4.5 직결은 깊이를 싣지 않아 깊이 상한이 없다 — 깊이 검사가 모델 id 로 가르는지 본다."""
    read = _reader(
        stat_judgment_model="haiku",
        anthropic_direct_api_key="sk-test",
        anthropic_haiku_model_id="claude-haiku-4-5",
        anthropic_structured_effort="xhigh",
    )

    assert assignment_errors(_STAT_ON_ANTHROPIC, read) == []
