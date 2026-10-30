"""로컬 미디어 북 넣기 — 측정 작업 DB 의 발행 버전에 인물·장면·칸(상황 설명, 더미 그림 자산)을 넣어 스토리 턴의 칸 판정
프롬프트에 실리게 한다. 판정기는 가짜 클라이언트다(유료 호출 0)."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import EndingJudgmentResult, ImageMatchJudgmentResult, StatRuleJudgmentResult
from api.core.config import settings
from api.llm.client import LLMCallContext, LLMClient
from factories import _clear_llm_override, _login_as, _override_llm_client, _story_with_setup
from memory_eval.media_book import SPEC_FILE, insert_media_book, load_spec


class _RecordingJudge(LLMClient):
    def __init__(self) -> None:
        self.prompts: dict[str, str] = {}

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        stop_sequences: list[str] | None = None,
        *,
        usage: LLMCallContext,
    ) -> AsyncIterator[str]:
        yield "도희가 모니터 앞에서 고개를 든다."

    async def generate_structured(
        self, prompt: str, response_schema: Any, images: Any = None, *, usage: LLMCallContext
    ) -> Any:
        self.prompts[usage.call_site] = prompt
        defaults: dict[type, Any] = {
            StatRuleJudgmentResult: StatRuleJudgmentResult(fired_rule_ids=[]),
            EndingJudgmentResult: EndingJudgmentResult(triggered=False),
            ImageMatchJudgmentResult: ImageMatchJudgmentResult(matched_image_entity_id=None),
        }
        return defaults[response_schema]


# 명세는 측정 데이터라 저장소 밖 데이터 폴더에 둔다 — 테스트는 지어낸 작은 명세를 그 자리에 쓴다.
_SYNTHETIC_SPEC = {
    "people": ["갑돌", "을순", "병태"],
    "scenes": ["복도", "옥상", "강당", "운동장"],
    "cells": [{"person": "갑돌", "scene": "옥상", "situation": "갑돌이 난간에 기대어 하늘을 본다."}],
}


def _data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / SPEC_FILE).write_text(json.dumps(_SYNTHETIC_SPEC, ensure_ascii=False), encoding="utf-8")
    return data_dir


def test_the_spec_is_read_from_the_data_dir_by_its_file_name(tmp_path: Path) -> None:
    assert load_spec(_data_dir(tmp_path) / SPEC_FILE) == _SYNTHETIC_SPEC


async def test_inserted_cells_reach_the_story_media_judgment_prompt(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user_id, content, setup = await _story_with_setup(db_session, opening_message="어서 와", paid_turns=1)
    version_id = content.current_published_version_id
    assert version_id is not None
    spec = {
        "people": ["도희", "유나", "세빈"],
        "scenes": ["동아리방", "편집실", "소극장", "새벽 호숫가"],
        "cells": [
            {"person": "도희", "scene": "편집실", "situation": "도희가 고장 난 선풍기의 나사를 하나씩 세어 본다."},
            {"person": "유나", "scene": "새벽 호숫가", "situation": "유나가 벤치에 남은 우산을 접어 난간에 걸어 둔다."},
        ],
    }
    report = await insert_media_book(db_session, version_id, user_id, spec)
    assert report == {"people": 3, "scenes": 4, "cells": 2}
    await db_session.commit()

    await _login_as(db_client, user_id)
    created = await db_client.post(
        "/chat-rooms", json={"contentId": str(content.id), "contentType": "story", "startingSetupId": str(setup.id)}
    )
    assert created.status_code == 201, created.text
    fake = _RecordingJudge()
    _override_llm_client(fake)
    try:
        sent = await db_client.post(f"/chat-rooms/{created.json()['id']}/messages", json={"content": "편집실에 간다"})
    finally:
        _clear_llm_override()
    assert sent.status_code == 200, sent.text

    prompt = fake.prompts["chat_media_book_image"]
    assert "인물=도희, 장면=편집실, 상황 설명=도희가 고장 난 선풍기의 나사를 하나씩 세어 본다." in prompt
    assert "인물=유나, 장면=새벽 호숫가, 상황 설명=유나가 벤치에 남은 우산을 접어 난간에 걸어 둔다." in prompt


async def test_a_version_that_already_has_a_media_book_is_refused(db_session: AsyncSession) -> None:
    user_id, content, _ = await _story_with_setup(db_session, opening_message=None)
    version_id = content.current_published_version_id
    assert version_id is not None
    spec = {
        "people": ["도희"],
        "scenes": ["동아리방"],
        "cells": [{"person": "도희", "scene": "동아리방", "situation": "x."}],
    }
    await insert_media_book(db_session, version_id, user_id, spec)
    with pytest.raises(SystemExit, match="이미"):
        await insert_media_book(db_session, version_id, user_id, spec)


def test_the_command_refuses_a_database_outside_the_measurement_prefix_before_touching_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from memory_eval_cli import main

    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@localhost:5432/ai_character_chat")
    data_dir = _data_dir(tmp_path)
    code = main(
        ["--run", str(tmp_path / "run"), "--data-dir", str(data_dir), "media-book", "--content-id", str(uuid.uuid4())]
    )
    assert code == 2
    assert "lm_eval_" in capsys.readouterr().err
    assert json.loads((data_dir / SPEC_FILE).read_text(encoding="utf-8")) == _SYNTHETIC_SPEC
