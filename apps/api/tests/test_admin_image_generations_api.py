import uuid
from datetime import UTC, datetime

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import AdminActionLog, Asset, AssetKind, AssetStatus, ImageGenerationRequest
from factories import _create_admin, _login_as, _login_as_admin, _make_user


async def _assert_requires_admin_session(
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
    method: str,
    path: str,
    json: dict[str, object] | None = None,
) -> None:
    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401

    user = _make_user()
    db_session.add(user)
    await db_session.commit()
    await _login_as(db_client, user.id)
    # 세션이 아예 안 서도 admin 401은 나오므로, 먼저 "이
    # 유저로는 실제로 인증된다"를 고정해야 위 무세션 401과 구분되는 명제가 남는다(공허한 통과 방지).
    assert (await db_client.get("/me")).status_code == 200

    resp = await db_client.request(method.upper(), path, json=json)
    assert resp.status_code == 401


async def _make_image_generation_request(
    db_session: AsyncSession, *, owner_user_id: uuid.UUID, **overrides: object
) -> ImageGenerationRequest:
    defaults: dict[str, object] = {
        "owner_user_id": owner_user_id,
        "prompt": "은밀한 프롬프트",
        "style": "soft_portrait",
        "aspect_ratio": "1:1",
        "model": "v1",
        "requested_count": 1,
        "status": "succeeded",
    }
    defaults.update(overrides)
    request_row = ImageGenerationRequest(**defaults)
    db_session.add(request_row)
    await db_session.flush()
    return request_row


# ---- 인증 -------------------------------------------------------------------


async def test_list_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 전역 목록에서 admin 인증 의존성을 빼먹으면 일반 유저도 볼 수 있다."""
    await _assert_requires_admin_session(db_client, db_session, "get", "/admin/image-generations")


async def test_view_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 사유 게이트 엔드포인트에서 admin 인증을 빼먹으면 일반 유저가 사유만
    적어 다른 유저의 프롬프트를 열람할 수 있다."""
    user_id = uuid.uuid4()
    await _assert_requires_admin_session(
        db_client,
        db_session,
        "post",
        f"/admin/users/{user_id}/image-generations/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )


async def test_more_requires_admin_session(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 더보기 엔드포인트가 admin 인증 없이 열리면 사유 게이트 자체가
    우회된다."""
    user_id = uuid.uuid4()
    await _assert_requires_admin_session(
        db_client, db_session, "get", f"/admin/users/{user_id}/image-generations"
    )


# ---- 404 --------------------------------------------------------------------


async def test_view_unknown_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 대상 유저 존재 확인을 빼먹으면 없는 유저 id로도 빈 응답이 200으로
    나간다."""
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{uuid.uuid4()}/image-generations/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert resp.status_code == 404


async def test_more_unknown_user_returns_404(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 더보기도 view와 같은 404 규약을 지켜야 한다 — 안 지키면 없는 유저
    id로 빈 목록이 200으로 나간다."""
    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(f"/admin/users/{uuid.uuid4()}/image-generations")
    assert resp.status_code == 404


# ---- 요청 바디 검증 ------------------------------------------------------------


async def test_view_blank_reason_text_returns_422_and_no_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: chat_view의 공백 사유 수동검증을 빼먹으면 공백 사유로도 열람 로그가
    쌓인다."""
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/image-generations/view",
        json={"reasonCategory": "other", "reasonText": "   "},
    )
    assert resp.status_code == 422

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert logs == []


# ---- 로그 --------------------------------------------------------------------


async def test_view_creates_exactly_one_action_log(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: record_admin_action을 잘못 부르거나 두 번 부르면 행 수·필드가
    열람 1회당 로그 1행이라는 규약과 어긋난다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_image_generation_request(db_session, owner_user_id=user.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/image-generations/view",
        json={"reasonCategory": "report-investigation", "reasonText": "신고 확인차 열람"},
    )
    assert resp.status_code == 200

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].action_type == "image-view"
    assert logs[0].target_user_id == user.id
    assert logs[0].reason_category == "report-investigation"
    assert logs[0].reason_text == "신고 확인차 열람"


async def test_view_response_includes_prompt_and_image_url(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 사유 게이트를 통과하고도 프롬프트·이미지 URL이 빠지면(열람
    응답에는 들어간다는 약속 위반) 관리자가 실제로 확인할 게 없다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    request_row = await _make_image_generation_request(
        db_session, owner_user_id=user.id, prompt="아주 은밀한 프롬프트", completed_count=1
    )
    asset_id = uuid.uuid4()
    db_session.add(
        Asset(
            id=asset_id,
            owner_user_id=user.id,
            storage_key=f"assets/generated/{asset_id}.png",
            kind=AssetKind.GENERATED,
            status=AssetStatus.READY,
            style="soft_portrait",
            request_id=request_row.id,
        )
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.post(
        f"/admin/users/{user.id}/image-generations/view",
        json={"reasonCategory": "other", "reasonText": "확인"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["prompt"] == "아주 은밀한 프롬프트"
    assert len(body["items"][0]["images"]) == 1
    assert body["items"][0]["images"][0]["assetId"] == str(asset_id)
    assert body["items"][0]["images"][0]["imageUrl"].startswith("http")


async def test_more_three_times_still_zero_log_rows(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """더보기(GET)를 몇 번 불러도 로그는 늘지 않는다.
    깨지는 시나리오: 더보기에 record_admin_action을 실수로 붙이면 3번 호출에 3행이 쌓인다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    await _make_image_generation_request(db_session, owner_user_id=user.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    for _ in range(3):
        resp = await db_client.get(f"/admin/users/{user.id}/image-generations")
        assert resp.status_code == 200

    logs = (
        await db_session.scalars(
            sa.select(AdminActionLog).where(AdminActionLog.target_user_id == user.id)
        )
    ).all()
    assert logs == []


# ---- 전역 목록에는 프롬프트·이미지 URL을 싣지 않는다 ------------------------------


async def test_list_response_omits_prompt_and_image_url(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: 전역 목록 스키마에 프롬프트나 이미지 URL 필드가 섞여
    들어가면 사유 게이트가 무의미해진다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    request_row = await _make_image_generation_request(
        db_session, owner_user_id=user.id, prompt="아주 은밀한 프롬프트-XYZ", completed_count=1
    )
    asset_id = uuid.uuid4()
    db_session.add(
        Asset(
            id=asset_id,
            owner_user_id=user.id,
            storage_key=f"assets/generated/{asset_id}.png",
            kind=AssetKind.GENERATED,
            status=AssetStatus.READY,
            style="soft_portrait",
            request_id=request_row.id,
        )
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/image-generations")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1  # 양성 대조 — 행이 실제로 있는데도 안 새는지 봐야 한다.

    raw_body = resp.text
    assert "아주 은밀한 프롬프트" not in raw_body
    assert '"prompt"' not in raw_body
    assert '"imageUrl"' not in raw_body


# ---- 필터 --------------------------------------------------------------------


async def test_list_filter_by_q_matches_only_target_owner(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: q 필터가 실제로 안 걸리면 검색어와 무관한 다른 유저의 요청도 함께
    나온다."""
    target = _make_user(email="target-owner@example.com", nickname="타겟유저")
    other = _make_user(email="other-owner@example.com", nickname="다른유저")
    db_session.add_all([target, other])
    await db_session.flush()
    await _make_image_generation_request(db_session, owner_user_id=target.id)
    await _make_image_generation_request(db_session, owner_user_id=other.id)
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get("/admin/image-generations", params={"q": "타겟유저"})
    assert resp.status_code == 200
    body = resp.json()
    assert [item["userId"] for item in body["items"]] == [str(target.id)]


async def test_list_filter_by_date_range_excludes_outside(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """깨지는 시나리오: from/to 경계가 실제로 안 걸리면 지정한 기간 밖의 요청도 함께
    나온다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    in_range = await _make_image_generation_request(
        db_session, owner_user_id=user.id, created_at=datetime(2026, 1, 5, tzinfo=UTC)
    )
    await _make_image_generation_request(
        db_session, owner_user_id=user.id, created_at=datetime(2026, 2, 1, tzinfo=UTC)
    )
    await db_session.commit()

    admin_payload = await _create_admin(db_session)
    await db_session.commit()
    await _login_as_admin(db_client, admin_payload)

    resp = await db_client.get(
        "/admin/image-generations", params={"from": "2026-01-01", "to": "2026-01-31"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [item["id"] for item in body["items"]] == [str(in_range.id)]
