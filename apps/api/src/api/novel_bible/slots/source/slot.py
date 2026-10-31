"""원작 정본 슬롯 — 소설이 기대는 원작의 작품 설정과 키워드북 노트를 읽기만 한다. 정본 기억 표에 쓰지 않고 모델을 부르지
않는다.

확정 때(`resolve`) 소설 생성과 같은 규칙으로 원작 버전을 고른다 — 방이 있으면 그 방이 고정한 버전, 방이 지워졌으면 원작의 지금
발행본. 확정 행에는 버전 id 와 입력 해시를 함께 남긴다. 해시만으로는 그때 어느 버전을 읽었는지 다시 만들 수 없고, 버전 id 만으로는
그 버전의 행이 나중에 바뀌었는지 알 수 없다. 작업 때(`load`) 확정 행의 버전으로 같은 글을 다시 만든다.

키워드북은 작품 버전 단위 노트(시작설정이 없는 것)만 읽는다. 소설에는 시작설정 칸이 없어, 방이 지워지면 어느 시작설정의 노트인지
정할 근거가 없다 — 시작설정 노트를 넣으면 같은 소설의 확정이 방이 있고 없음에 따라 다른 원작 입력을 읽는다. 트리거로 고르지도
않는다 — 채팅 턴의 대화를 훑어 노트를 고르는 규칙이라 화 단위 확정에는 훑을 턴이 없다.

노트 글의 이름 자리(`{{user}}`)는 작품 설정과 같은 규칙으로 소설 주인공 이름으로 바꾼다 — 이름이 비면 대체어, 바로 뒤 조사는
이름에 맞춘다. 이미지 태그는 지우지 않는다 — 채팅도 노트 글은 이름만 바꿔 싣고, 이미지 태그를 쓰는 빌더 글(`content/media_tags.py`
모듈 docstring 의 목록)에 노트는 없다. 돌려주는 글과 해시가 같은 글을 가리키도록 빈 노트 거르기와 해시도 바꾼 글로 한다."""

import hashlib
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.novel import Novel
from api.db.models.story import KeywordNote
from api.novel_bible.core.types import SourceCanon, SourceCanonRef
from api.novel_bible.ids import SlotId

# 소설 생성이 작품 설정을 읽는 규칙을 그대로 부른다. 같은 규칙을 여기 다시 쓰면 생성 쪽만 바뀌어 둘이 다른 버전을 읽기 쉽다.
from api.novelize.inputs import _version_id, load_work_setting
from api.novelize.source import novel_prompt_names

logger = logging.getLogger(__name__)


def _input_hash(version_id: uuid.UUID, work_setting: str, keyword_notes: dict[uuid.UUID, str]) -> str:
    """버전 id·작품 설정 글·노트 (id, 글) 목록의 sha256. JSON 배열로 이어 붙여, 글 안의 어떤 문자도 칸 사이 경계로 읽히지
    않게 한다."""
    payload = [str(version_id), work_setting, [[str(note_id), text] for note_id, text in keyword_notes.items()]]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


async def _read(session: AsyncSession, novel: Novel, version_id: uuid.UUID) -> SourceCanon:
    work_setting = await load_work_setting(session, novel, version_id)
    # `load_work_setting` 이 작품 설정에 쓰는 것과 같은 식이다. 이름 없는 소설에서 예외를 내는 주인공 이름 검사는 쓰지 않는다 —
    # 확정 입구와 어드민 라우트가 그 예외를 받지 않는다.
    names = novel_prompt_names(protagonist_name=novel.protagonist_name or "", character_name=novel.character_name)
    rows = (
        await session.execute(
            select(KeywordNote.id, KeywordNote.info_text)
            .where(KeywordNote.content_version_id == version_id, KeywordNote.starting_setup_id.is_(None))
            # 채팅이 노트를 싣는 순서와 같다. 같은 버전에 같은 entity_id 가 둘이면 순서가 정해지지 않아 해시가 흔들리므로 끝에
            # 행 id 로 정한다.
            .order_by(KeywordNote.order, KeywordNote.entity_id, KeywordNote.id)
        )
    ).all()
    expanded = ((row.id, names.expand(row.info_text)) for row in rows)
    keyword_notes = {note_id: text for note_id, text in expanded if text.strip()}
    return SourceCanon(
        ref=SourceCanonRef(
            content_version_id=version_id, input_hash=_input_hash(version_id, work_setting, keyword_notes)
        ),
        work_setting=work_setting,
        keyword_notes=keyword_notes,
    )


async def _novel(session: AsyncSession, novel_id: uuid.UUID) -> Novel:
    novel = await session.get(Novel, novel_id)
    assert novel is not None  # 확정 입구가 같은 트랜잭션에서 소설을 확인했고, 소설이 지워지면 확정 행도 CASCADE 로 사라진다
    return novel


class SourceCanonSlot:
    id: SlotId = "source"

    async def resolve(self, session: AsyncSession, novel_id: uuid.UUID) -> SourceCanonRef | None:
        """원작 버전이 없으면(원작이 지워졌거나 발행본이 없음) None — 원작 입력 없이 확정한다."""
        novel = await _novel(session, novel_id)
        version_id = await _version_id(session, novel)
        if version_id is None:
            return None
        return (await _read(session, novel, version_id)).ref

    async def load(self, session: AsyncSession, novel_id: uuid.UUID, ref: SourceCanonRef) -> SourceCanon:
        """확정 행의 버전으로 글을 다시 만든다. 해시가 확정 때와 다르면 그 뒤에 글이 바뀐 것이다(그 버전의 설정·노트 행이
        고쳐졌거나, 이름 자리를 채우는 소설 주인공 이름이 바뀌었거나, 글을 만드는 규칙 — 이미지 태그 제거·이름 치환 — 의 코드가
        그 사이 배포로 바뀌었다) — 지금 글을 그대로 쓰고(돌려주는 해시도 지금 글의 것) 경고만 남긴다.

        이름은 확정 행에 남지 않아, 확정과 작업 사이에 이름이 바뀌면 새 이름의 글로 진행한다. 원작 근거의 글자 위치는 이름을 바꾼
        글 기준이라, 이름이 바뀐 뒤 다시 만든 글에서는 이미 저장된 위치가 어긋날 수 있다(이름 길이와 조사가 달라진다). 저장된
        위치를 지금 글과 대조하는 코드는 이 어긋남을 근거가 사라진 것으로 읽지 않아야 한다."""
        canon = await _read(session, await _novel(session, novel_id), ref.content_version_id)
        if canon.ref.input_hash != ref.input_hash:
            logger.warning("소설 %s 의 원작 버전 %s 입력이 확정 뒤에 바뀌었다", novel_id, ref.content_version_id)
        return canon
