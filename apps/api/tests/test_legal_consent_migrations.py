"""법무 문서 변경 안내 이관(`fc3ca58a473b`)과 동의 이력 백필(`d6abfd9f92ce`) 데이터 마이그레이션의 검증.

마이그레이션 자체는 다시 돌리지 않는다. 안내 추출은 순수 함수라 문자열로 바로 부르고, 백필 함수는 테스트마다 롤백되는
`db_session` 의 커넥션에 `run_sync` 로 부른다. 세션 스키마는 이미 `upgrade head` 상태이고 시드 약관·처리방침
(`2026-09-06`)이 게시돼 있다."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models import LegalDocument, UserLegalConsent
from factories import _make_user

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(revision: str) -> ModuleType:
    (path,) = _VERSIONS_DIR.glob(f"{revision}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_NOTICE = _load("fc3ca58a473b")
_HISTORY = _load("d6abfd9f92ce")

_HEAD = "# 개인정보처리방침\n\n**버전** 2026-10-17\n\n"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param(
            _HEAD + "## 주요 변경 내용\n\n- 첫째\n- 둘째\n\n### 세부\n\n내용\n\n## 제1조 (목적)\n\n본문\n\n## 주요 변경 내용\n\n뒤",
            "- 첫째\n- 둘째\n\n### 세부\n\n내용",
            id="section-before-next-heading",
        ),
        pytest.param(_HEAD + "## 제1조 (목적)\n\n본문", None, id="no-section"),
        pytest.param(_HEAD + "## 제1조\n\n본문\n\n## 주요 변경 내용\n\n끝 절 내용\n", "끝 절 내용", id="section-at-end"),
        pytest.param(_HEAD + "## 주요 변경 내용\n\n\n## 제1조\n", None, id="empty-section"),
    ],
)
def test_extract_change_notice_takes_the_first_section_without_its_heading(body: str, expected: str | None) -> None:
    """첫 `## 주요 변경 내용` 절만, 제목 줄을 빼고 다음 `## ` 제목 앞까지(하위 `###` 는 절 안이다) 옮긴다. 깨지는 시나리오:
    다음 조항이나 뒤에 다시 나온 같은 제목의 절까지 안내에 섞여 재동의 화면에 법적 본문 조각이 요약처럼 나온다."""
    assert _NOTICE.extract_change_notice(body) == expected


async def _history_of(db_session: AsyncSession, user_id: object) -> list[tuple[str, str | None, datetime]]:
    rows = await db_session.execute(
        sa.select(UserLegalConsent.consent, LegalDocument.version, UserLegalConsent.consented_at)
        .join(LegalDocument, LegalDocument.id == UserLegalConsent.legal_document_id)
        .where(UserLegalConsent.user_id == user_id)
        .order_by(UserLegalConsent.consent)
    )
    return [tuple(row) for row in rows.all()]


async def test_backfill_writes_one_row_per_recorded_consent_of_active_members_only(db_session: AsyncSession) -> None:
    """활성 회원마다 `users` 의 동의 칸 셋을 게시본 id 로 찾아 1행씩 넣는다. 동의 시각이 없거나 게시본에 없는 버전은
    건너뛰고 그 수를 돌려준다. 탈퇴 회원은 넣지 않는다. 깨지는 시나리오: 탈퇴해서 파기했어야 할 회원의 이력이 생기거나,
    있지도 않은 판에 동의한 행이 만들어진다."""
    agreed_at = datetime.now(UTC) - timedelta(days=3)
    active = _make_user(terms_agreed_at=agreed_at, privacy_agreed_at=agreed_at, transfer_agreed_at=agreed_at)
    no_transfer = _make_user(transfer_version=None, transfer_agreed_at=None)
    unknown_terms = _make_user(terms_version="2020-01-01")
    withdrawn = _make_user(deleted_at=datetime.now(UTC))
    db_session.add_all([active, no_transfer, unknown_terms, withdrawn])
    await db_session.flush()
    before = await db_session.scalar(sa.select(sa.func.count()).select_from(UserLegalConsent))

    connection = await db_session.connection()
    skipped = await connection.run_sync(_HISTORY.backfill_consent_history)

    assert await _history_of(db_session, active.id) == [
        ("collection", "2026-09-06", agreed_at),
        ("terms", "2026-09-06", agreed_at),
        ("transfer", "2026-09-06", agreed_at),
    ]
    assert [row[0] for row in await _history_of(db_session, no_transfer.id)] == ["collection", "terms"]
    assert [row[0] for row in await _history_of(db_session, unknown_terms.id)] == ["collection", "transfer"]
    assert await _history_of(db_session, withdrawn.id) == []
    assert skipped == 1
    after = await db_session.scalar(sa.select(sa.func.count()).select_from(UserLegalConsent))
    assert after == (before or 0) + 3 + 2 + 2


async def test_consent_history_rejects_an_unknown_consent_unit(db_session: AsyncSession) -> None:
    """동의 단위 칸은 세 값만 받는다(CHECK). 깨지는 시나리오: 처리방침 동의를 옛 문서 이름(`privacy`)으로 적은 행이 생겨
    어느 동의를 받았는지 가를 수 없게 된다."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    document = await db_session.scalar(sa.select(LegalDocument).where(LegalDocument.kind == "privacy"))
    assert document is not None
    db_session.add(
        UserLegalConsent(
            user_id=user.id, legal_document_id=document.id, consent="privacy", consented_at=datetime.now(UTC)
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_seeded_reconsent_editions_were_moved_to_document_consent_units(db_session: AsyncSession) -> None:
    """이관은 기존 재동의 판을 약관은 `terms`, 처리방침은 `collection`·`transfer` 로 옮긴다(지금까지 처리방침 재동의는 두
    동의를 함께 다시 받았다). 깨지는 시나리오: 처리방침 재동의 판이 한 단위만 걸려, 국외이전 동의가 옛 회원을 놓친다."""
    rows = (
        await db_session.execute(
            sa.select(LegalDocument.kind, LegalDocument.reconsent_scopes).where(
                LegalDocument.version == "2026-09-06", LegalDocument.status == "published"
            )
        )
    ).all()
    assert sorted((kind, list(scopes)) for kind, scopes in rows) == [
        ("privacy", ["collection", "transfer"]),
        ("terms", ["terms"]),
    ]
