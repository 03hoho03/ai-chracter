"""격리 DB 에 story 레인의 새 게시 세트를 만든다 — 현행 측정 기준 세트의 사본에서 요약 접기 지시문
(`memory_summary` · both · `instruction`) 한 행의 [요약 규칙] 목록만 바꾼다.

어드민 게시(`admin/prompts.py:publish_prompt_set`)와 같은 함수·같은 행 구성을 쓴다: 게시 전 검증
`_validate_prompt_draft_for_publish`, 버전 번호 `_next_published_version`(레인 무관 전역 최대 + 1),
커밋 뒤 캐시 무효화 `invalidate_active_prompt_set`. 어드민 경로와 다른 점은 둘이다 — 이 격리 DB 에는
어드민 계정이 없어 관리자 조치 기록을 남기지 않고, 레인의 초안 행을 만들지도 덮어쓰지도 않는다
(기존 초안이 없고, 측정 밖의 행을 늘리지 않으려고).

기본은 ROLLBACK 시험 실행이고 --commit 을 줘야 반영한다.
사용(cwd apps/api): uv run --env-file .env python scripts/experiments/filmclub_longturn/publish_l1_set.py [--commit]
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v6_fix_texts as T

from api.admin.prompts import _next_published_version, _validate_prompt_draft_for_publish
from api.chat.prompt_set_cache import invalidate_active_prompt_set
from api.db.models.prompt import PromptSection, PromptSet
from api.db.session import async_session_factory

NOTE = (
    "격리 장거리 측정 전용: 요약 규칙을 [지금]·[관계]·[지난 일: 최신 사건부터] 세 부분으로 바꾼다 — 서버의 "
    "1,500자 절단이 가장 오래된 사건을 자르게 하려는 것(memory_summary instruction 한 행만, 직전 v17 4f446070)"
)


async def main(commit: bool) -> None:
    base_id = uuid.UUID(T.BASE_STORY_SET_ID)
    async with async_session_factory() as db:
        base = await db.get(PromptSet, base_id)
        assert base is not None
        if base.lane != "story" or base.status != "published":
            raise SystemExit("멈춤: 기준 세트가 story 게시본이 아니다")
        active = (
            await db.scalars(
                select(PromptSet)
                .where(PromptSet.lane == "story", PromptSet.status == "published")
                .order_by(PromptSet.published_at.desc())
                .limit(1)
            )
        ).one()
        if active.id != base_id:
            raise SystemExit(f"멈춤: story 활성 세트가 기준 세트가 아니다({active.id} v{active.version})")
        base_sections = (await db.scalars(select(PromptSection).where(PromptSection.prompt_set_id == base_id))).all()

        next_version = await _next_published_version(db)
        published = PromptSet(
            id=uuid.uuid4(),
            version=next_version,
            status="published",
            lane="story",
            note=NOTE,
            user_label=base.user_label,
            story_assistant_label=base.story_assistant_label,
            story_example_label=base.story_example_label,
            character_assistant_label=base.character_assistant_label,
            published_at=datetime.now(UTC),
        )
        sections: list[PromptSection] = []
        changed = 0
        for s in base_sections:
            body = s.body
            if (s.channel, s.scope, s.slot, s.variant) == ("memory_summary", "both", "instruction", ""):
                body = T.replace_once(body, T.SUMMARY_RULES_OLD, T.SUMMARY_RULES_NEW, "요약 지시문")
                changed += 1
            sections.append(
                PromptSection(
                    id=uuid.uuid4(),
                    prompt_set_id=published.id,
                    channel=s.channel,
                    scope=s.scope,
                    slot=s.slot,
                    variant=s.variant,
                    body=body,
                    conditional=s.conditional,
                    order=s.order,
                )
            )
        if changed != 1:
            raise SystemExit(f"멈춤: 바꾼 섹션이 {changed}개다")

        # 어드민 게시와 같은 검증을 새 세트에 건다(슬롯 집합·플레이스홀더·order 등).
        _validate_prompt_draft_for_publish(published, sections, lane="story")

        db.add(published)
        await db.flush()
        db.add_all(sections)
        await db.flush()
        print(f"l1_set_id\t{published.id}")
        print(f"l1_set_version\t{published.version}")
        print(f"l1_set_published_at\t{published.published_at.isoformat() if published.published_at else None}")
        print(f"sections\t{len(sections)}")
        if commit:
            await db.commit()
            # 어드민 게시처럼 커밋 뒤에 지운다 — 앞에서 지우면 그 사이의 캐시 미스가 옛 세트를 다시 넣는다.
            await invalidate_active_prompt_set("story")
            print("반영함, prompt_set:active:story 무효화")
        else:
            await db.rollback()
            print("시험 실행(ROLLBACK)")


if __name__ == "__main__":
    asyncio.run(main("--commit" in sys.argv[1:]))
