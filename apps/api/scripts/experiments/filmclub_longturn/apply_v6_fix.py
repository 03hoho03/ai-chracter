"""격리 DB 의 복제 조감독 v5 를 새 발행 버전(번호 6, 이하 v6-fix)으로 복제하고 그 버전에만 수정 문안을 넣는다.

자식 행 복제는 손 SQL 이 아니라 발행 경로가 쓰는 `_clone_story_children` 을 그대로 부른다 — entity_id 보존,
키워드 노트의 시작설정 물리 FK 재매핑까지 앱 코드가 한다. 그 함수가 복제하지 않는 `story_version_details` 는
발행 경로와 같은 열 목록으로 복사한다. 번호는 발행 경로와 같은 규칙(작품의 최대 번호 + 1)이고, 버전 행에는
DB 제약이 없어 번호·게시 시각 누락을 DB 가 막지 못하므로 스크립트가 단언한다.

수정은 v6-fix 행에만 한다. 바꿀 자리마다 원래 값이 기대와 정확히 같은지 먼저 확인하고(다르면 멈춤) 바꾼다.
마지막에 작품의 현행 발행 버전을 v6-fix 로 옮긴다 — 새 대화방은 이 값으로 버전을 고정한다.

기본은 ROLLBACK 시험 실행이고 --commit 을 줘야 반영한다.
사용(cwd apps/api): uv run --env-file .env python scripts/experiments/filmclub_longturn/apply_v6_fix.py [--commit]
"""

import asyncio
import copy
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v6_fix_texts as T

from api.content.router import _clone_story_children
from api.db.models.content import Content, ContentVersion
from api.db.models.story import (
    Ending,
    EndingRule,
    EndingRuleGroup,
    EndingRuleOperator,
    KeywordNote,
    LogicalOp,
    SituationNote,
    StartingSetup,
    StatDef,
    StoryVersionDetail,
)
from api.db.session import async_session_factory


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"멈춤: {message}")


async def main(commit: bool) -> None:
    content_id = uuid.UUID(T.REPLICA_CONTENT_ID)
    v5_id = uuid.UUID(T.REPLICA_V5_ID)
    async with async_session_factory() as db:
        content = await db.get(Content, content_id)
        check(content is not None, "복제 작품이 없다")
        assert content is not None
        check(content.current_published_version_id == v5_id, "현행 발행 버전이 복제 v5 가 아니다")
        check(not content.has_unpublished_changes, "미발행 변경 플래그가 켜져 있다")
        v5 = await db.get(ContentVersion, v5_id)
        assert v5 is not None
        check(v5.version_number == 5 and v5.published_at is not None, "복제 v5 의 번호·게시 시각이 기대와 다르다")

        # 번호는 발행 경로와 같은 규칙: 이 작품 버전의 최대 번호 + 1.
        latest = await db.scalar(
            select(func.max(ContentVersion.version_number)).where(ContentVersion.content_id == content_id)
        )
        check(latest == 5, f"이 작품의 최대 버전 번호가 5 가 아니다({latest}) — 이미 만든 적이 있는지 본다")
        new_version = ContentVersion(
            content_id=content_id,
            detail_description=v5.detail_description,
            version_number=(latest or 0) + 1,
            published_at=datetime.now(UTC),
        )
        db.add(new_version)
        await db.flush()
        check(new_version.version_number == 6, "새 버전 번호가 6 이 아니다")
        check(new_version.published_at is not None, "새 버전의 게시 시각이 비었다")

        detail = await db.get(StoryVersionDetail, v5_id)
        assert detail is not None
        new_detail = StoryVersionDetail(
            content_version_id=new_version.id,
            name=detail.name,
            one_liner=detail.one_liner,
            thumbnail_asset_id=detail.thumbnail_asset_id,
            prompt_template=detail.prompt_template,
            setting_text=detail.setting_text,
            development_example=detail.development_example,
            custom_prompt=detail.custom_prompt,
            development_examples=detail.development_examples,
            user_goal=detail.user_goal,
            rules=detail.rules,
            default_user_name=detail.default_user_name,
        )
        db.add(new_detail)
        await _clone_story_children(db, v5_id, new_version.id)
        await db.flush()

        setups = (
            await db.scalars(select(StartingSetup).where(StartingSetup.content_version_id == new_version.id))
        ).all()
        check(len(setups) == 1, f"v6-fix 시작설정이 {len(setups)}개다")
        setup = setups[0]

        # 설정: 날짜 넘김 문장 하나를 바꾼다.
        new_detail.setting_text = T.replace_once(new_detail.setting_text, T.SETTING_OLD, T.SETTING_NEW, "설정")

        # 스탯 「상영회까지」 설명.
        countdown = (
            await db.scalars(
                select(StatDef).where(
                    StatDef.starting_setup_id == setup.id, StatDef.entity_id == uuid.UUID(T.COUNTDOWN_STAT)
                )
            )
        ).one()
        check(countdown.description == T.COUNTDOWN_DESC_OLD, "「상영회까지」 설명 원문이 기대와 다르다")
        countdown.description = T.COUNTDOWN_DESC_NEW

        # 상황 노트: 단계 경계 조건과 두 노트 본문.
        notes = {
            n.entity_id: n
            for n in (await db.scalars(select(SituationNote).where(SituationNote.starting_setup_id == setup.id))).all()
        }
        check(len(notes) == 7, f"상황 노트가 {len(notes)}개다")
        for note_id, changes in T.STAGE_RULE_CHANGES.items():
            note = notes[uuid.UUID(note_id)]
            rules = copy.deepcopy(note.condition_rules)
            by_id = {r["id"]: r for r in rules}
            for rule_id, old_op, old_th, new_op, new_th in changes:
                rule = by_id[rule_id]
                check(
                    rule["operator"] == old_op and rule["threshold"] == old_th,
                    f"{note.name} 규칙 {rule_id} 원래 값이 {rule['operator']} {rule['threshold']}",
                )
                rule["operator"] = new_op
                rule["threshold"] = new_th
            note.condition_rules = rules
        day = notes[uuid.UUID(T.NOTE_DAY)]
        check(
            [(r["operator"], r["threshold"]) for r in day.condition_rules] == [("lte", 0.0)],
            "「상영회 당일」 조건이 lte 0 하나가 아니다",
        )
        early = notes[uuid.UUID(T.NOTE_EARLY)]
        check(early.info_text == T.EARLY_INFO_OLD, "「준비 초반」 본문 원문이 기대와 다르다")
        early.info_text = T.EARLY_INFO_NEW
        check(day.info_text == T.DAY_INFO_OLD, "「상영회 당일」 본문 원문이 기대와 다르다")
        day.info_text = T.DAY_INFO_NEW

        # 엔딩 규칙.
        endings = {
            e.name: e for e in (await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id))).all()
        }
        check(len(endings) == 5, f"엔딩이 {len(endings)}개다")
        groups = (
            await db.scalars(
                select(EndingRuleGroup).where(EndingRuleGroup.ending_id.in_([e.id for e in endings.values()]))
            )
        ).all()
        check(not groups, "엔딩 규칙 그룹이 있다(기대 0)")
        added_rules: list[tuple[str, uuid.UUID, uuid.UUID]] = []
        for name, route_rule_entity in T.ROUTE_ENDINGS.items():
            ending = endings[name]
            rules = (await db.scalars(select(EndingRule).where(EndingRule.ending_id == ending.id))).all()
            check(len(rules) == 1, f"{name} 규칙이 {len(rules)}행이다")
            old = rules[0]
            check(
                str(old.entity_id) == route_rule_entity
                and old.operator == EndingRuleOperator.GTE
                and old.threshold == Decimal("55")
                and old.next_op is None
                and old.order == 0,
                f"{name} 기존 규칙이 기대(GTE 55, NULL, order 0)와 다르다",
            )
            # 기존 행은 id·entity_id 를 그대로 두고 뒤로 민다. 같은 order 를 두 행이 가지면 정렬 결과가
            # DB 반환 순서에 달린다.
            old.order = 1
            new_rule = EndingRule(
                id=uuid.uuid4(),
                entity_id=uuid.uuid4(),
                ending_id=ending.id,
                stat_def_entity_id=uuid.UUID(T.COUNTDOWN_STAT),
                operator=EndingRuleOperator.LTE,
                threshold=Decimal("0.0"),  # 빌더 저장 경로(float → numeric)와 같은 표기
                next_op=LogicalOp.AND,
                order=0,
            )
            db.add(new_rule)
            added_rules.append((name, new_rule.id, new_rule.entity_id))

        all_crew = endings[T.ALL_CREW_ENDING]
        crew_rules = {
            str(r.entity_id): r
            for r in (await db.scalars(select(EndingRule).where(EndingRule.ending_id == all_crew.id))).all()
        }
        check(
            set(crew_rules) == {T.ALL_CREW_KEEP_RULE, *T.ALL_CREW_DROP_RULES},
            "「모두의 조감독」 규칙 entity_id 집합이 기대와 다르다",
        )
        keep = crew_rules[T.ALL_CREW_KEEP_RULE]
        check(
            keep.stat_def_entity_id == uuid.UUID(T.COUNTDOWN_STAT)
            and keep.operator == EndingRuleOperator.LTE
            and keep.threshold == Decimal("0")
            and keep.next_op == LogicalOp.AND
            and keep.order == 0,
            "「모두의 조감독」 남길 규칙이 기대(상영회까지 LTE 0 AND order 0)와 다르다",
        )
        for drop_id in T.ALL_CREW_DROP_RULES:
            drop = crew_rules[drop_id]
            check(
                drop.operator == EndingRuleOperator.LT and drop.threshold == Decimal("55"),
                f"「모두의 조감독」 지울 규칙 {drop_id} 가 LT 55 가 아니다",
            )
            await db.delete(drop)
        # 남는 한 행이 목록의 끝이므로 이음을 비운다. AND 로 끝나는 규칙 목록은 만들지 않는다.
        keep.next_op = None

        # 키워드 노트 비밀 문장.
        knotes = {
            str(n.entity_id): n
            for n in (
                await db.scalars(select(KeywordNote).where(KeywordNote.content_version_id == new_version.id))
            ).all()
        }
        for note_id, (old_sentence, new_sentence) in T.KEYWORD_CHANGES.items():
            knote = knotes[note_id]
            knote.info_text = T.replace_once(knote.info_text, old_sentence, new_sentence, f"키워드 노트 {knote.name}")

        content.current_published_version_id = new_version.id
        await db.flush()

        print(f"v6_fix_id\t{new_version.id}")
        print(f"v6_fix_version_number\t{new_version.version_number}")
        print(f"v6_fix_published_at\t{new_version.published_at.isoformat()}")
        print(f"v6_fix_starting_setup_id\t{setup.id}")
        print(f"starting_setup_entity_id\t{setup.entity_id}")
        for name, rule_id, entity_id in added_rules:
            print(f"added_rule\t{name}\t{rule_id}\t{entity_id}")
        if commit:
            await db.commit()
            print("반영함")
        else:
            await db.rollback()
            print("시험 실행(ROLLBACK)")


if __name__ == "__main__":
    asyncio.run(main("--commit" in sys.argv[1:]))
