"""채팅 레인 Gemini 체인의 어드민 저장·게시·복원이 옛 소설화 세 채널을 따로 다루지 않는다는 것의 검증.

소설 문안은 `novel` 레인에서만 고치고 읽는다. 채팅 두 레인 Gemini 체인에 남겨 두었던 옛 소설화 행은 마이그레이션이 뺐고, 어드민은
그 행을 더는 갈아 끼우거나 숨기지 않는다 — 채팅 체인에 그 채널을 넣으면 다른 낯선 채널처럼 게시 검증이 "잉여"로 막는다."""

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat.prompt_builder import PromptLane
from api.db.models.prompt import PromptSection, PromptSet
from factories import _create_admin, _login_as_admin

_NOVEL_CHANNELS = frozenset({"novelize_boundary", "novelize_chapter", "novelize_revise"})
_LANES: tuple[PromptLane, ...] = ("story", "character")


def _load(revision: str) -> ModuleType:
    (path,) = (Path(__file__).resolve().parents[1] / "migrations" / "versions").glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 소설화 행을 지우기 전 채팅 Gemini 체인의 마지막 게시본 — 인상 생성 문안 리비전의 세트다.
_OLD_SET_IDS: dict[str, uuid.UUID] = {
    lane: _load("6558ab4d3dbc").NEW_SET_IDS[(lane, "gemini")] for lane in _LANES
}


async def _login_new_admin(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)


async def _stored_sections(db_session: AsyncSession, set_id: uuid.UUID) -> list[PromptSection]:
    return list(
        (
            await db_session.scalars(
                sa.select(PromptSection)
                .where(PromptSection.prompt_set_id == set_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


def _synthetic_novel_rows() -> list[dict[str, object]]:
    return [
        {
            "channel": "novelize_chapter",
            "scope": "both",
            "slot": slot,
            "variant": "",
            "body": f"[합성 소설 문안] {slot}",
            "conditional": False,
            "order": order,
        }
        for order, slot in enumerate(("instruction", "turn_context"))
    ]


@pytest.mark.parametrize("lane", _LANES)
async def test_chat_gemini_draft_has_no_novel_channels_or_hints(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane
) -> None:
    """깨지는 시나리오: 채팅 체인 화면이 소설 채널 칸이나 그 자리표시자 힌트를 다시 그려 운영자가 읽히지 않는 문안을 고친다."""
    await _login_new_admin(db_client, db_session)

    resp = await db_client.get(f"/admin/prompt-sets/{lane}/draft")

    assert resp.status_code == 200
    body = resp.json()
    assert not {s["channel"] for s in body["sections"]} & _NOVEL_CHANNELS
    assert not {h["channel"] for h in body["allowedPlaceholders"]} & _NOVEL_CHANNELS


async def test_chat_gemini_draft_keeps_sent_novel_rows_as_they_are_and_publish_rejects_them(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """저장은 받은 행을 그대로 저장하고 응답에도 그대로 싣는다(서버가 활성판 값으로 바꾸거나 숨기지 않는다). 그 초안은 채팅 체인에
    없는 채널을 담아 게시가 슬롯 집합 검사(잉여)로 막힌다. 깨지는 시나리오: 서버가 소설 행을 조용히 다른 값으로 바꿔 저장해 운영자가 보낸 것과 저장된
    것이 다르거나, 채팅 체인에 소설 행을 다시 게시한다."""
    await _login_new_admin(db_client, db_session)
    shown = (await db_client.get("/admin/prompt-sets/story/draft")).json()
    sent = _synthetic_novel_rows()

    put = await db_client.put(
        "/admin/prompt-sets/story/draft", json={"labels": shown["labels"], "sections": [*shown["sections"], *sent]}
    )

    assert put.status_code == 200, put.text
    returned = sorted(
        (s["slot"], s["body"]) for s in put.json()["sections"] if s["channel"] in _NOVEL_CHANNELS
    )
    assert returned == sorted((str(row["slot"]), str(row["body"])) for row in sent)
    stored = await _stored_sections(db_session, uuid.UUID(put.json()["id"]))
    assert sorted((s.slot, s.body) for s in stored if s.channel in _NOVEL_CHANNELS) == returned

    published = await db_client.post("/admin/prompt-sets/story/publish", json={"note": "소설 행 포함"})
    assert published.status_code == 422
    assert published.json()["detail"]["rule"] == "R-1"


@pytest.mark.parametrize("lane", _LANES)
async def test_chat_gemini_publish_carries_no_novel_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession, lane: PromptLane
) -> None:
    """화면이 보여 준 그대로 저장한 초안은 소설 행 없이 게시된다. 깨지는 시나리오: 게시가 직전 게시본의 소설 행을 다시 끼워 넣거나,
    게시 검증이 여전히 소설 행을 요구해 채팅 체인 게시가 "누락"으로 막힌다."""
    await _login_new_admin(db_client, db_session)
    shown = (await db_client.get(f"/admin/prompt-sets/{lane}/draft")).json()
    put = await db_client.put(
        f"/admin/prompt-sets/{lane}/draft", json={"labels": shown["labels"], "sections": shown["sections"]}
    )
    assert put.status_code == 200, put.text

    published = await db_client.post(f"/admin/prompt-sets/{lane}/publish", json={"note": "채팅만"})

    assert published.status_code == 200, published.text
    stored = await _stored_sections(db_session, uuid.UUID(published.json()["id"]))
    assert stored
    assert not {s.channel for s in stored} & _NOVEL_CHANNELS


async def test_restoring_a_novel_channel_into_a_chat_chain_is_refused_as_not_in_the_chain(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """옛 채팅 게시본에는 소설 채널이 있지만 지금 채팅 체인에는 그 채널이 없다 — 다른 낯선 채널과 같은 이유로 거절하고 아무것도
    쓰지 않는다. 깨지는 시나리오: 복원이 소설 행을 채팅 초안에 들여와 그 초안의 게시가 막히거나, 소설 채널만 따로 다루던 거절
    규칙이 남아 화면이 없는 규칙 이름을 받는다."""
    await _login_new_admin(db_client, db_session)
    old = await db_session.get(PromptSet, _OLD_SET_IDS["story"])
    assert old is not None and old.status == "published"

    resp = await db_client.post(f"/admin/prompt-sets/{old.id}/sections/novelize_chapter/restore", json={})

    assert resp.status_code == 422
    assert resp.json()["detail"]["rule"] == "restore-channel-not-in-chain"
    drafts = await db_session.scalar(
        sa.select(sa.func.count()).select_from(PromptSet).where(PromptSet.status == "draft")
    )
    assert drafts == 0
