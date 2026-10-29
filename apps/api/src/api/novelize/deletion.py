"""소설과 그 아래 행을 지우는 단 한 곳, 마지막 묶음을 지우는 곳, 숨겨 남긴 소설(작가가 지웠거나 탈퇴한 팔린 소설)에서 작가만
쓰던 것을 지우는 곳, 그리고 더 쓸 데가 없어진 AI 수정 지시문·결과 본문을 비우는 곳(과 그 미리보기가 낡았는지 가르는 판정).

소설 단독 삭제와 회원 탈퇴가 `delete_novels` 를 같이 쓴다. 두 경로가 자식 목록을 따로 가지면 테이블이 늘 때 한쪽에만
더해지기 쉽고, 빠진 쪽은 소설 DELETE 가 FK 위반으로 500 이 된다. 뼈대 테이블(작업·개정·화·소설)에는 `ON DELETE
CASCADE` 가 없어 자식부터 지운다. 묶음·인물·등장 인물·스냅샷·읽은 위치와 노벨 공개 상태·화 공개본·텍스트 심사 기록·
독자 읽은 자리·좋아요·홈 노벨 지정·화 댓글, 정본 기억 표들은 부모를 지우면 함께 지워지는 cascade 지만(옛 판 코드로 되돌렸을 때 그 코드가 이 테이블들을 몰라도 지워지게 한 것이다), 여기서는
cascade 에 기대지 않고 순서를 직접 적어 잠금·삭제 순서를 고정한다. 예외는 화 공개본의 판 행과 소설의 무료 번호 기억이다 —
다른 표가 가리키지 않는 말단 표라 여기서 따로 지우지 않고 화·소설을 지울 때 cascade 로 함께 지워진다. 노벨·노벨 댓글 신고는 지우지 않는다 — 소설·화·댓글
칸이 `SET NULL` 이라 대상이 지워지면 칸만 비고, 신고와 증거 사본은 보유 기간 동안 남는다.

화 개정의 삽화 배치는 개정보다 먼저 직접 지운다(개정 FK 가 cascade 지만 기대지 않는다). 지운 배치가 쓰던 업로드 삽화가 이제
아무도 쓰지 않는 것이면 그 자산 행도 지우고, 저장소에서 지울 키를 호출자가 넘긴 `freed_storage_keys` 에 더한다 — 저장소는 호출자가
커밋 뒤에 지운다(`illustrations.delete_storage_objects`). 이 인자를 필수로 둔 것은 새 호출자가 파일 정리를 빠뜨리지 않게 하려는
것이다.

이 모듈은 라우터를 import 하지 않는다 — `auth/withdrawal.py` 가 import 해도 순환이 생기지 않게."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Delete,
    Select,
    SQLColumnExpression,
    Update,
    delete,
    exists,
    literal_column,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.novelize.block_edits import BlockEdit, has_pending, stale_marked
from api.novelize.job_variants import kinds_where
from api.novelize.text import split_paragraphs
from api.db.models.novel import (
    HomeNovelCuration,
    Novel,
    NovelBatch,
    NovelChapter,
    NovelChapterCharacter,
    NovelChapterEdition,
    NovelChapterIllustration,
    NovelChapterRevision,
    NovelChapterPublication,
    NovelCharacter,
    NovelComment,
    NovelEpisodeOutline,
    NovelJob,
    NovelLike,
    NovelOutline,
    NovelPublication,
    NovelReaderPosition,
    NovelReadingPosition,
    NovelSceneBlock,
    NovelScreening,
    NovelSnapshot,
    NovelSourceSection,
    NovelSourceSelection,
)
from api.db.models.novel_bible import (
    NovelBibleAdaptationCandidate,
    NovelBibleCommit,
    NovelBibleEntity,
    NovelBibleEvidence,
    NovelBibleExpiration,
    NovelBibleFinding,
    NovelBibleJob,
    NovelBibleRevision,
)
from api.db.models.novel_bible_events import NovelBibleEvent, NovelBibleEventRelation
from api.db.models.novel_bible_facts import NovelBibleFact
from api.db.models.novel_bible_knowledge import NovelBibleKnowledge
from api.novelize.illustrations import delete_unused_illustration_assets, drop_placements, assets_used_by


async def delete_novels(db: AsyncSession, novel_ids: Sequence[uuid.UUID], *, freed_storage_keys: list[str]) -> None:
    """`novel_ids` 소설들을 작업 → 화 잠금 → 정본 기억 → 읽은 위치(소유자·노벨 독자)·화 댓글 → 스냅샷 → 등장 인물 → 인물 → 텍스트 심사 기록 → 화
    공개본 → 개정의 삽화 배치 → 개정 → 장면 블록 → 화 → 묶음 → 좋아요·홈 노벨 지정 → 공개 상태 → 장면 구성안 → 전체 구성안 → 구간
    선택 → 소설 순으로 지우고, 끝에 이제 아무도 쓰지 않는
    업로드 삽화를 지운다. 커밋은 호출부가 한다. 화 공개본은 개정을 가리키므로 개정보다 먼저다.

    작업 행이 맨 앞인 이유는 둘이다. 작업이 화·개정을 FK 로 가리키므로 먼저 지워야 하고, 진행 중 작업이 성공을
    저장하는 트랜잭션과 겹쳤을 때도 안전해진다 — 성공 쪽이 작업 행을 잡고 있으면 이 DELETE 가 기다렸다가 뒤 문장들이
    새로 커밋된 화까지 보고 지우고, 이쪽이 먼저 지웠으면 성공 쪽의 조건부 상태 전이가 0행이 되어 화를 넣지 않는다.
    진행 중 작업의 환불은 이 함수가 하지 않는다 — 소설 단독 삭제는 부르기 전에 환불하고, 탈퇴는 잔액을 통째로
    소멸시키므로 환불하지 않는다.

    화를 지우기 전에 먼저 잠근다. 직접 수정·되돌리기·AI 수정 적용은 화 행을 잠근 채 새 개정을 넣는데, 잠그지 않으면
    아래 개정 DELETE 가 아직 커밋되지 않은 새 개정을 못 보고 지나가고 화 DELETE 가 그 개정의 FK 에 걸린다. 기다린 뒤의
    개정 DELETE 는 새 문장이라 커밋된 새 개정까지 본다. 읽은 위치를 화 잠금 뒤에 지우는 것도 같은 이유다 — 위치 저장은
    화가 있는지 확인하며 화 행에 키 공유 잠금을 거므로, 화를 먼저 쥐면 그 저장이 끝나기를 기다렸다가 함께 지운다. 화 댓글과
    정본 기억 쓰기도 같다(둘 다 화 FK 검사로 화 행에 키 공유 잠금을 건다 — `_bible_row_deletes`).

    각 DELETE 는 `db.execute` 로 그 자리에서 실행되는 SQL 문이라 적은 순서대로 나간다. ORM 객체를 `db.delete()` 로
    모아 한 번에 flush 할 때처럼 SQLAlchemy 가 순서를 바꾸지 않으므로 단계 사이 `flush()` 는 필요 없다. 되돌리기
    개정이 같은 테이블의 앞 개정을 가리키지만 한 문장 안에서 함께 지우므로 FK 위반이 나지 않는다."""
    if not novel_ids:
        return
    chapter_ids = select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids))
    await db.execute(delete(NovelJob).where(NovelJob.novel_id.in_(novel_ids)))
    await db.execute(select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids)).with_for_update())
    for statement in _bible_row_deletes(novel_ids):
        await db.execute(statement)
    await db.execute(delete(NovelReadingPosition).where(NovelReadingPosition.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelReaderPosition).where(NovelReaderPosition.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelComment).where(NovelComment.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelSnapshot).where(NovelSnapshot.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelChapterCharacter).where(NovelChapterCharacter.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelCharacter).where(NovelCharacter.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelScreening).where(NovelScreening.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelChapterPublication).where(NovelChapterPublication.novel_id.in_(novel_ids)))
    uploads = await drop_placements(
        db, select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id.in_(chapter_ids))
    )
    await db.execute(delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelSceneBlock).where(NovelSceneBlock.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapter).where(NovelChapter.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelBatch).where(NovelBatch.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelLike).where(NovelLike.novel_id.in_(novel_ids)))
    await db.execute(delete(HomeNovelCuration).where(HomeNovelCuration.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelPublication).where(NovelPublication.novel_id.in_(novel_ids)))
    await _delete_outlines(db, novel_ids)
    await _delete_source_selections(db, novel_ids)
    await db.execute(delete(Novel).where(Novel.id.in_(novel_ids)))
    freed_storage_keys += await delete_unused_illustration_assets(db, uploads)


def _bible_row_deletes(novel_ids: Sequence[uuid.UUID]) -> list[Delete]:
    """소설들의 정본 기억 행을 지우는 문장들, 낼 차례대로 — 만료·근거·검사 결과·각색 후보 → 지식 → 사실 → 회상 관계 → 사건 →
    리비전 → 작업 → 확정 → 개체. 소설·화·개정·확정·리비전·개체와 회상 관계의 사건을 가리키는 FK 는 cascade 이고, 표끼리 잇는
    사슬 칸(대체한 앞 항목·앞 리비전·사실의 시작 사건·지식의 알게 된 사건)은 SET NULL 이지만, 어느 쪽에도 기대지 않고 자식부터
    지운다. 작업은 확정보다 먼저 지운다 — 정본 기억 작업을 받거나 끝내는 쪽도 작업 행 → 확정 행 순으로 잡아야 둘이 서로를
    기다리지 않는다. 개정 DELETE 의 cascade 에 맡기면 확정 행이 먼저 잠긴다.

    부르는 쪽은 화 행을 잠근 뒤에 낸다. 화를 가리키는 정본 기억 행을 넣는 쓰기는 화 FK 검사로 화 행에 키 공유 잠금을 잡으므로,
    진행 중인 쓰기가 끝나기를 기다렸다가 그 쓰기가 넣은 행까지 지운다. 정본 기억 커밋은 화 행 잠금을 다른 행보다 먼저 잡아야
    한다 — 확정 행을 쥔 채 화 행을 기다리면, 화 행을 쥔 채 확정 행 DELETE 를 기다리는 이쪽과 교착한다."""
    return [
        delete(NovelBibleExpiration).where(NovelBibleExpiration.novel_id.in_(novel_ids)),
        delete(NovelBibleEvidence).where(NovelBibleEvidence.novel_id.in_(novel_ids)),
        delete(NovelBibleFinding).where(NovelBibleFinding.novel_id.in_(novel_ids)),
        delete(NovelBibleAdaptationCandidate).where(NovelBibleAdaptationCandidate.novel_id.in_(novel_ids)),
        delete(NovelBibleKnowledge).where(NovelBibleKnowledge.novel_id.in_(novel_ids)),
        delete(NovelBibleFact).where(NovelBibleFact.novel_id.in_(novel_ids)),
        delete(NovelBibleEventRelation).where(NovelBibleEventRelation.novel_id.in_(novel_ids)),
        delete(NovelBibleEvent).where(NovelBibleEvent.novel_id.in_(novel_ids)),
        delete(NovelBibleRevision).where(NovelBibleRevision.novel_id.in_(novel_ids)),
        delete(NovelBibleJob).where(NovelBibleJob.novel_id.in_(novel_ids)),
        delete(NovelBibleCommit).where(NovelBibleCommit.novel_id.in_(novel_ids)),
        delete(NovelBibleEntity).where(NovelBibleEntity.novel_id.in_(novel_ids)),
    ]


def _bible_row_deletes_of_chapters(chapter_ids: Sequence[uuid.UUID]) -> list[Delete]:
    """지우는 화들에서 나온 정본 기억 — 그 화들의 확정과, 그 확정의 리비전에 매달린 항목·근거·만료·각색 후보와 확정의 검사
    결과·작업 — 을 지우는 문장들. 차례와 잠금은 `_bible_row_deletes` 와 같다. 개체는 남긴다(인물 카드를 묶음 삭제가 남기는 것과
    같은 이유 — 다른 화에도 나온다). 지운 리비전을 앞 리비전으로 가리키던 다른 화의 리비전은 FK 가 그 칸을 비운다."""
    commit_ids = select(NovelBibleCommit.id).where(NovelBibleCommit.chapter_id.in_(chapter_ids))
    revision_ids = select(NovelBibleRevision.id).where(NovelBibleRevision.commit_id.in_(commit_ids))
    return [
        delete(NovelBibleExpiration).where(NovelBibleExpiration.revision_id.in_(revision_ids)),
        delete(NovelBibleEvidence).where(NovelBibleEvidence.created_revision_id.in_(revision_ids)),
        delete(NovelBibleFinding).where(NovelBibleFinding.commit_id.in_(commit_ids)),
        delete(NovelBibleAdaptationCandidate).where(
            NovelBibleAdaptationCandidate.created_revision_id.in_(revision_ids)
        ),
        delete(NovelBibleKnowledge).where(NovelBibleKnowledge.created_revision_id.in_(revision_ids)),
        delete(NovelBibleFact).where(NovelBibleFact.created_revision_id.in_(revision_ids)),
        delete(NovelBibleEventRelation).where(NovelBibleEventRelation.created_revision_id.in_(revision_ids)),
        delete(NovelBibleEvent).where(NovelBibleEvent.created_revision_id.in_(revision_ids)),
        delete(NovelBibleRevision).where(NovelBibleRevision.commit_id.in_(commit_ids)),
        delete(NovelBibleJob).where(NovelBibleJob.commit_id.in_(commit_ids)),
        delete(NovelBibleCommit).where(NovelBibleCommit.chapter_id.in_(chapter_ids)),
    ]


def _selection_ids(novel_ids: Sequence[uuid.UUID]) -> Select[tuple[uuid.UUID]]:
    return select(NovelSourceSelection.id).where(NovelSourceSelection.novel_id.in_(novel_ids))


async def _delete_outlines(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> None:
    """장면 블록 → 장면 구성안 → 전체 구성안 순으로 지운다(소설·화·구성안 FK 가 cascade 지만 기대지 않는다). 판매된 소설의
    작가 전용 데이터 정리(`strip_author_only_data`)도 같은 순서로 지운다."""
    episode_outline_ids = select(NovelEpisodeOutline.id).where(NovelEpisodeOutline.novel_id.in_(novel_ids))
    await db.execute(delete(NovelSceneBlock).where(NovelSceneBlock.episode_outline_id.in_(episode_outline_ids)))
    await db.execute(delete(NovelEpisodeOutline).where(NovelEpisodeOutline.novel_id.in_(novel_ids)))
    await db.execute(delete(NovelOutline).where(NovelOutline.novel_id.in_(novel_ids)))


async def _delete_source_selections(db: AsyncSession, novel_ids: Sequence[uuid.UUID]) -> None:
    """구간 선택의 구간 행 → 선택 순으로 지운다(선택 FK 가 cascade 지만 기대지 않는다)."""
    await db.execute(delete(NovelSourceSection).where(NovelSourceSection.selection_id.in_(_selection_ids(novel_ids))))
    await db.execute(delete(NovelSourceSelection).where(NovelSourceSelection.novel_id.in_(novel_ids)))


async def strip_author_only_data(
    db: AsyncSession, novel_ids: Sequence[uuid.UUID], *, freed_storage_keys: list[str]
) -> int:
    """숨겨 남긴 소설들(작가가 지웠거나 탈퇴한 팔린 소설)에서 독자가 읽는 것만 남기고 작가만 쓰던 것을 지운다. 바꾼 행 수를 돌려준다(0 이면 이미
    정리된 소설이다 — 몇 번 불러도 결과가 같다). 커밋은 호출부가 한다.

    남는 것은 독자·운영자 경로가 읽는 것뿐이다 — 공개 상태 행, 화 공개본과 판 행(누가 어느 판을 샀든), 그 둘이 가리키는 개정과
    그 화 행, 소설의 원작 사본·권리 잠금 칸, 그리고 독자가 남긴 읽은 자리·댓글·좋아요와 구매·심사·신고 기록. 독자에게 나가는 제목·
    소개·화 제목·작가의 말은 모두 공개 때 얼린 사본이라 작업본 칸을 비워도 화면이 그대로다.

    지우거나 비우는 것: 작업 행, 작가 읽은 자리, 스냅숏, 등장 인물·인물 카드, 정본 기억(원고에서 뽑은 사실 값·사건 요지·믿음 —
    작가만 쓰는 파생 내용이다), 공개본·판 행이 없는 화(공개되지 않은 화 — 그
    화의 심사 기록·읽은 자리·댓글과 함께)와 화가 남지 않은 묶음, 공개본·판 행이 가리키지 않는 개정(초고·수정 이력), 남는 개정의
    되돌리기 원본 칸, 남는 화의 작업본 제목·요약·작가의 말, 소설의 설정 노트·주인공 이름·작업본 제목과 소개·편집 보드·표지, 지운
    개정의 삽화 배치와 그 배치만 쓰던 업로드 삽화, 작가가 고른 대화 구간 기록(구간 선택)과 구성안(전체 구성안·장면 구성안·남는
    화의 장면 블록) — 이 둘은 소설 행이 남아 cascade 로는 지워지지 않는다. 남는 화의 장면 구성안 칸은 FK 가 없어 그대로 둔다.

    잠금과 순서는 `delete_novels` 와 같다 — 작업 행을 먼저 지우고(진행 중 작업의 조건부 전이가 0행이 된다) 화 행을 잠근 뒤
    정본 기억·읽은 자리·댓글·개정을 지운다. 남는 화·개정을 가리키는 정본 기억은 cascade 로도 지워지지 않으므로 화 잠금 뒤의 이
    DELETE 가 유일한 길이다. 비우는 UPDATE 는 이미 빈 행을 고르지 않아 바꾼 행 수가 "정리할 것이 있었는가"를 뜻한다."""
    if not novel_ids:
        return 0
    chapter_ids = select(NovelChapter.id).where(NovelChapter.novel_id.in_(novel_ids))
    kept_revision_ids = select(NovelChapterPublication.revision_id).where(
        NovelChapterPublication.novel_id.in_(novel_ids)
    ).union(select(NovelChapterEdition.revision_id).where(NovelChapterEdition.novel_id.in_(novel_ids)))
    kept_chapter_ids = select(NovelChapterPublication.chapter_id).where(
        NovelChapterPublication.novel_id.in_(novel_ids)
    ).union(select(NovelChapterEdition.chapter_id).where(NovelChapterEdition.novel_id.in_(novel_ids)))
    dropped_chapter_ids = select(NovelChapter.id).where(
        NovelChapter.novel_id.in_(novel_ids), NovelChapter.id.not_in(kept_chapter_ids)
    )
    changed = 0

    async def run(statement: Delete | Update) -> None:
        # 바꾼 행 수는 `.rowcount` 대신 돌려받은 행으로 센다(`Result` 가 mypy strict 에서 그 속성을 노출하지 않는다).
        nonlocal changed
        changed += len((await db.execute(statement.returning(literal_column("1")))).all())

    await run(delete(NovelJob).where(NovelJob.novel_id.in_(novel_ids)))
    await db.execute(chapter_ids.with_for_update())
    for statement in _bible_row_deletes(novel_ids):
        await run(statement)
    await run(delete(NovelReadingPosition).where(NovelReadingPosition.novel_id.in_(novel_ids)))
    await run(delete(NovelSnapshot).where(NovelSnapshot.novel_id.in_(novel_ids)))
    await run(delete(NovelChapterCharacter).where(NovelChapterCharacter.chapter_id.in_(chapter_ids)))
    await run(delete(NovelCharacter).where(NovelCharacter.novel_id.in_(novel_ids)))
    await run(delete(NovelReaderPosition).where(NovelReaderPosition.chapter_id.in_(dropped_chapter_ids)))
    await run(delete(NovelComment).where(NovelComment.chapter_id.in_(dropped_chapter_ids)))
    await run(delete(NovelScreening).where(NovelScreening.chapter_id.in_(dropped_chapter_ids)))
    # 남는 개정이 지울 개정을 되돌리기 원본으로 가리키면 개정 DELETE 가 FK 위반이다. 되돌리기 이력은 작가 기록이라 모두 비운다.
    await run(
        update(NovelChapterRevision)
        .where(
            NovelChapterRevision.chapter_id.in_(chapter_ids),
            NovelChapterRevision.reverted_from_revision_id.is_not(None),
        )
        .values(reverted_from_revision_id=None)
    )
    dropped_revision_ids = select(NovelChapterRevision.id).where(
        NovelChapterRevision.chapter_id.in_(chapter_ids), NovelChapterRevision.id.not_in(kept_revision_ids)
    )
    uploads = set((await db.scalars(assets_used_by(dropped_revision_ids))).all())
    await run(delete(NovelChapterIllustration).where(NovelChapterIllustration.revision_id.in_(dropped_revision_ids)))
    await run(
        delete(NovelChapterRevision).where(
            NovelChapterRevision.chapter_id.in_(chapter_ids), NovelChapterRevision.id.not_in(kept_revision_ids)
        )
    )
    await run(delete(NovelChapter).where(NovelChapter.id.in_(dropped_chapter_ids)))
    await run(
        delete(NovelBatch).where(
            NovelBatch.novel_id.in_(novel_ids),
            ~select(NovelChapter.id).where(NovelChapter.batch_id == NovelBatch.id).exists(),
        )
    )
    await run(
        update(NovelChapter)
        .where(
            NovelChapter.novel_id.in_(novel_ids),
            or_(
                NovelChapter.title.is_not(None),
                NovelChapter.title_edited_at.is_not(None),
                NovelChapter.summary.is_not(None),
                NovelChapter.author_note != "",
            ),
        )
        .values(title=None, title_edited_at=None, summary=None, author_note="")
    )
    await run(
        update(Novel)
        .where(
            Novel.id.in_(novel_ids),
            or_(
                Novel.setting_notes != "",
                Novel.protagonist_name.is_not(None),
                Novel.title.is_not(None),
                Novel.title_edited_at.is_not(None),
                Novel.synopsis != "",
                Novel.board_layout != text("'{}'::jsonb"),
                Novel.cover_asset_id.is_not(None),
            ),
        )
        .values(
            setting_notes="",
            protagonist_name=None,
            title=None,
            title_edited_at=None,
            synopsis="",
            board_layout={},
            cover_asset_id=None,
        )
    )
    episode_outline_ids = select(NovelEpisodeOutline.id).where(NovelEpisodeOutline.novel_id.in_(novel_ids))
    await run(delete(NovelSceneBlock).where(NovelSceneBlock.episode_outline_id.in_(episode_outline_ids)))
    await run(delete(NovelEpisodeOutline).where(NovelEpisodeOutline.novel_id.in_(novel_ids)))
    await run(delete(NovelOutline).where(NovelOutline.novel_id.in_(novel_ids)))
    await run(delete(NovelSourceSection).where(NovelSourceSection.selection_id.in_(_selection_ids(novel_ids))))
    await run(delete(NovelSourceSelection).where(NovelSourceSelection.novel_id.in_(novel_ids)))
    freed_storage_keys += await delete_unused_illustration_assets(db, uploads)
    return changed


async def delete_batch(
    db: AsyncSession, *, novel_id: uuid.UUID, batch_id: uuid.UUID, freed_storage_keys: list[str]
) -> None:
    """묶음 하나와 그 화들을 지운다. 진행 중 작업 확인·"마지막 묶음" 판정·사용자 잠금은 호출자가 먼저 한다(커밋도).

    작업 행은 지우지 않고 그 화들을 가리키는 칸(화·기준 개정·결과 개정)과 AI 수정 지시문·결과 본문·여러 문단 수정 칸만 비운다 — 같은
    시작 메시지의 하루 재시도 상한이 작업 행 수로 세므로, 지우면 묶음을 지웠다 다시 만드는 것으로 상한이 풀린다. 차감
    기록의 작업 쪽 짝도 남는다. 작업의 개정 참조는 모두 그 작업이 가리키는 화의 개정이라, 화로 골라 셋을 함께 비운다.

    그다음 화를 잠그고(`delete_novels` 와 같은 이유) 그 화들에서 나온 정본 기억·읽은 위치(소유자·노벨 독자)·화 댓글·등장 인물·텍스트
    심사 기록·화 공개본·개정의 삽화 배치·개정·장면 블록·화·묶음 순으로 지우고, 끝에 이제 아무도 쓰지 않는 업로드 삽화를 지운다. 인물 카드는 남긴다 — 사용자가 메모를 적은 카드일 수 있고, 다른 화에도 나온다. 소설의 공개 상태 행도 남긴다 —
    지우는 것은 마지막 묶음뿐이라 남은 공개 화는 여전히 1화부터 이어지고, 공개한 화가 모두 지워져도 소설 제목·소개 사본과
    운영자 조치는 소설에 남아야 한다(다시 화를 공개하면 같은 행을 쓴다).

    잠금 순서는 작업 행 → 화 행이다(`delete_novels` 와 같다). 화 id 는 잠금 없이 고른다 — 호출자가 사용자 행을 쥐고 있어
    같은 묶음에 화를 더하거나 빼는 경로(묶음 저장·삭제)가 끼어들 수 없다. 화를 먼저 잠그고 작업 행을 고치면, 작업 행을 쥔
    채 화를 기다리는 AI 수정 적용과 서로를 기다려 한쪽이 교착 오류로 끊긴다.

    정본 기억은 지운 화에서 나온 것을 이력째 지운다(`_bible_row_deletes_of_chapters`) — 지운 화의 내용은 함께 사라져야 한다(아래
    "즉시 삭제"와 같은 이유). 그 화의 리비전이 사라져 리비전 번호에 구멍이 나지만, 머리는 최대 번호라 구멍과 무관하다.

    스냅샷은 남기되 지운 화의 항목을 `{chapterId, deleted: true}` 로 줄인다. 화 제목·요약·작가의 말은 지운 화의
    내용이라 지울 때 함께 사라져야 하고(처리방침의 "즉시 삭제"), 항목 자리를 남기는 것은 그 스냅샷을 복원할 때 화가
    지워졌다는 사실을 알리기 위해서다."""
    chapter_ids = list((await db.scalars(select(NovelChapter.id).where(NovelChapter.batch_id == batch_id))).all())
    await db.execute(
        update(NovelJob)
        .where(NovelJob.chapter_id.in_(chapter_ids))
        .values(
            chapter_id=None,
            base_revision_id=None,
            result_revision_id=None,
            instruction=None,
            result_text=None,
            block_edit=None,
        )
    )
    await db.execute(select(NovelChapter.id).where(NovelChapter.id.in_(chapter_ids)).with_for_update())
    for statement in _bible_row_deletes_of_chapters(chapter_ids):
        await db.execute(statement)
    await db.execute(delete(NovelReadingPosition).where(NovelReadingPosition.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelReaderPosition).where(NovelReaderPosition.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelComment).where(NovelComment.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapterCharacter).where(NovelChapterCharacter.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelScreening).where(NovelScreening.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapterPublication).where(NovelChapterPublication.chapter_id.in_(chapter_ids)))
    uploads = await drop_placements(
        db, select(NovelChapterRevision.id).where(NovelChapterRevision.chapter_id.in_(chapter_ids))
    )
    await db.execute(delete(NovelChapterRevision).where(NovelChapterRevision.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelSceneBlock).where(NovelSceneBlock.chapter_id.in_(chapter_ids)))
    await db.execute(delete(NovelChapter).where(NovelChapter.id.in_(chapter_ids)))
    await _shrink_snapshot_entries(db, novel_id, {str(chapter_id) for chapter_id in chapter_ids})
    await db.execute(delete(NovelBatch).where(NovelBatch.id == batch_id))
    freed_storage_keys += await delete_unused_illustration_assets(db, uploads)


async def _shrink_snapshot_entries(db: AsyncSession, novel_id: uuid.UUID, removed: set[str]) -> None:
    """소설의 스냅샷마다 `removed` 화의 항목을 `{chapterId, deleted: true}` 로 바꿔 쓴다. 그런 항목이 없는 스냅샷은
    건드리지 않는다."""
    snapshots = (
        await db.execute(
            select(NovelSnapshot.id, NovelSnapshot.payload).where(NovelSnapshot.novel_id == novel_id).with_for_update()
        )
    ).all()
    for snapshot_id, payload in snapshots:
        entries: list[dict[str, Any]] = payload.get("chapters", [])
        if not any(entry.get("chapterId") in removed for entry in entries):
            continue
        shrunk = [
            {"chapterId": entry["chapterId"], "deleted": True} if entry.get("chapterId") in removed else entry
            for entry in entries
        ]
        await db.execute(
            update(NovelSnapshot).where(NovelSnapshot.id == snapshot_id).values(payload={**payload, "chapters": shrunk})
        )


def ai_edit_preview_is_fresh(
    base_revision_id: SQLColumnExpression[uuid.UUID | None] | uuid.UUID,
    current_hash: SQLColumnExpression[str] | str,
) -> ColumnElement[bool]:
    """AI 수정 미리보기가 아직 쓸 수 있는가 — 기준 개정의 본문 해시가 지금 개정의 본문 해시(`current_hash`)와 같다.
    미리보기를 비우기·결과 저장·미적용 목록·적용이 모두 이 판정 하나를 쓴다. 한 자리만 다른 기준이면 저장은 성공했는데
    곧바로 비워지거나, 목록에 없는데 적용은 되는 미리보기가 생긴다.

    개정 id 가 아니라 본문 해시로 보는 이유: 같은 글로 되돌리기처럼 글이 그대로인 새 개정 위에서는 작업의 문단 범위와
    결과 본문(범위 밖은 기준 문단을 그대로 이어 붙였다)이 지금 개정에도 똑같이 맞는다. 해시가 같으면 문단 배열이 같다.
    적용 결과의 블록 id 는 기준 개정이 아니라 잠근 지금 개정에서 잇는다.

    SQL 식이라 조회 조건에 그대로 넣거나 `select(...)` 로 값 하나를 읽는다. 기준 개정이 없으면(칸이 비었거나 행이
    없으면) 거짓이다. 기준 개정은 별칭으로 읽는다 — 지금 개정 해시를 개정 표의 하위 조회로 넘겨도 그 조회가 이 식의
    개정 행에 묶이지 않게."""
    base = aliased(NovelChapterRevision)
    return exists().where(base.id == base_revision_id, base.content_hash == current_hash)


async def erase_stale_ai_edit_previews(db: AsyncSession, chapter_id: uuid.UUID) -> None:
    """장 `chapter_id` 의 지금 개정과 글이 다른 개정을 기준으로 한(`ai_edit_preview_is_fresh` 가 거짓인), 적용도
    버리기도 안 한 AI 수정 결과의 지시문과 결과 본문을 비운다. 여러 문단 수정은 화 전체가 아니라 패치 단위로 본다
    (`_erase_stale_patches`). 커밋은 호출부가 한다.

    그런 결과는 적용하면 409 이고 상세의 미적용 목록에도 나오지 않아, 사용자가 버리기를 누를 길이 없다 — 비우지
    않으면 소설을 지울 때까지 아무도 볼 수 없는 사본으로 남는다. 작업 행은 남긴다(하루 재시도 상한을 행 수로 센다).

    새 개정을 커밋한 **뒤 별도 트랜잭션에서** 부른다. 개정을 쌓는 경로는 장 행을 잠그고, 적용은 작업 행 → 장 행 순서로
    잠근다 — 장을 쥔 채 작업 행을 고치면 같은 장의 적용과 서로를 기다린다. 따로 돌면 작업 행 잠금만 쥐고, 지금 커밋된
    현재 개정으로 판정하므로 몇 번 돌아도 같다. AI 수정 결과 저장은 이 함수를 부르지 않는다 — 저장할 때 장 행을
    잠그고 같은 판정으로 확인해, 낡은 결과는 아예 성공으로 남기지 않는다."""
    current_hash = (
        select(NovelChapterRevision.content_hash)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
        .scalar_subquery()
    )
    await db.execute(
        update(NovelJob)
        .where(
            NovelJob.chapter_id == chapter_id,
            NovelJob.kind.in_(kinds_where(call_site="novelize_revise")),
            NovelJob.status == "succeeded",
            NovelJob.result_revision_id.is_(None),
            NovelJob.dismissed_at.is_(None),
            NovelJob.result_text.is_not(None),
            ~ai_edit_preview_is_fresh(NovelJob.base_revision_id, current_hash),
        )
        # 결과 본문이 있는 작업만 고르므로 여러 문단 수정(패치 칸이 있는 작업은 결과 본문이 늘 비어 있다)은 여기 오지 않는다 —
        # 패치 칸은 늘 비어 있지만, 지시문·결과를 비우는 자리마다 패치 칸도 다룬다는 약속을 지키려 함께 적는다.
        .values(instruction=None, result_text=None, block_edit=None)
    )
    await _erase_stale_patches(db, chapter_id)


async def _erase_stale_patches(db: AsyncSession, chapter_id: uuid.UUID) -> None:
    """여러 문단 수정의 패치 단위 비우기 — 장 `chapter_id` 의 대기 패치 중 지금 개정에 쓸 수 없게 된 것(그 블록이 없거나 글이
    바뀜)을 낡음으로 바꾸고 문단을 비운다. 같은 작업의 다른 패치는 그 블록이 그대로면 산다. 대기 수정안이 하나도 남지 않은 작업은
    지시문까지 비운다(처리방침의 즉시 삭제). 낡음은 영구다 — 같은 글로 돌아와도 비운 문단은 되살릴 수 없다.

    판정은 패치 칸을 파이썬으로 읽어야 해서 작업 행을 `FOR NO KEY UPDATE` 로 잡는다(id 차례 — 두 비우기가 같은 행들을 서로 다른
    차례로 잡아 교착하지 않게). 장 행은 잡지 않는다(위 비우기와 같은 이유). 지금 개정은 작업 행을 잡은 **뒤에** 읽는다 — 앞에서
    읽으면 기다리는 동안 그 개정 위에서 맡겨 저장된 작업을 옛 개정으로 판정해 멀쩡한 패치를 낡음으로 만든다. 그 뒤에 쌓인 개정은
    그 개정의 비우기가 다시 본다."""
    jobs = (
        await db.scalars(
            select(NovelJob)
            .where(
                NovelJob.chapter_id == chapter_id,
                NovelJob.kind.in_(kinds_where(call_site="novelize_revise")),
                NovelJob.status == "succeeded",
                NovelJob.dismissed_at.is_(None),
                NovelJob.block_edit.contains({"patches": [{"state": "pending"}]}),
            )
            .order_by(NovelJob.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    if not jobs:
        return
    current = await db.scalar(
        select(NovelChapterRevision)
        .where(NovelChapterRevision.chapter_id == chapter_id)
        .order_by(NovelChapterRevision.revision_no.desc())
        .limit(1)
    )
    if current is None:
        return
    paragraphs = split_paragraphs(current.body)
    for job in jobs:
        assert job.block_edit is not None  # 위 조건으로 걸렀다
        edit = BlockEdit.model_validate(job.block_edit)
        marked = stale_marked(edit, current.block_ids, paragraphs)
        if marked == edit:
            continue
        values: dict[str, Any] = {"block_edit": marked.to_json()}
        if not has_pending(marked):
            values["instruction"] = None
        await db.execute(update(NovelJob).where(NovelJob.id == job.id).values(**values))
