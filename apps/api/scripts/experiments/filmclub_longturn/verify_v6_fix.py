"""v6-fix 의 엔딩 규칙·상황 노트 조건을 경계값 표로 평가하고, 발행 검증을 v6-fix 에 건다. LLM·쓰기 없음.

평가는 실채팅이 쓰는 경로 그대로다 — 엔딩은 DB 에서 규칙을 order 로 재구성하는 `_ending_rule_items` →
`evaluate_rule_list`, 상황 노트는 실채팅과 같은 정렬(order, entity_id)로 읽은 행을 `RULE_LIST_ADAPTER` 로
되읽어 `_situation_note_texts` 에 넣는다. 규칙을 손으로 만들면 DB 정렬·JSONB 되읽기를 건너뛰게 된다.
발행 검증은 빌더 발행이 쓰는 `_load_story_publish_draft` 를 그대로 불러 400(빠진 칸)이 나는지만 본다 —
스크립트로 만든 버전은 빌더 검증을 거치지 않았기 때문이다.

기대값은 아래 함수로 먼저 적어 두고 실측과 대조한다. 하나라도 어긋나면 종료 코드 1.
사용(cwd apps/api): uv run --env-file .env python scripts/experiments/filmclub_longturn/verify_v6_fix.py <v6-fix id>
"""

import asyncio
import sys
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v6_fix_texts as T

from api.chat.ending_rules import evaluate_rule_list
from api.chat.router import RULE_LIST_ADAPTER, _ending_rule_items, _situation_note_texts
from api.content.router import _load_story_publish_draft
from api.db.models.content import Content, ContentVersion
from api.db.models.story import Ending, SituationNote, StartingSetup
from api.db.session import async_session_factory

ROUTE_STAT = {
    "다음 작품의 첫 장": T.DOHEE_STAT,
    "컷 소리가 난 뒤에도": T.YUNA_STAT,
    "오프닝은 새벽 호수": T.SEBIN_STAT,
}
AFFECTIONS = (T.DOHEE_STAT, T.YUNA_STAT, T.SEBIN_STAT)
COUNTDOWNS = (42.0, 29.0, 28.5, 28.0, 8.0, 7.5, 7.0, 1.0, 0.5, 0.0)
STAGES = ("준비 초반", "촬영 기간", "상영회 직전", "상영회 당일")


def expected_ending(name: str, stats: dict[str, float]) -> bool:
    day = stats[T.COUNTDOWN_STAT] <= 0
    if name in ROUTE_STAT:
        return day and stats[ROUTE_STAT[name]] >= 55
    if name == "크레디트 맨 끝 줄":
        return day and all(stats[s] <= 35 for s in AFFECTIONS)
    if name == T.ALL_CREW_ENDING:
        return day
    raise SystemExit(f"모르는 엔딩 {name}")


def expected_stage(countdown: float) -> str:
    if countdown > 28:
        return "준비 초반"
    if countdown > 7:
        return "촬영 기간"
    if countdown > 0:
        return "상영회 직전"
    return "상영회 당일"


def fmt(v: float) -> str:
    return f"{v:g}"


async def main(v6_id: uuid.UUID) -> None:
    bad: list[str] = []
    async with async_session_factory() as db:
        (setup,) = (await db.scalars(select(StartingSetup).where(StartingSetup.content_version_id == v6_id))).all()
        endings = (
            await db.scalars(select(Ending).where(Ending.starting_setup_id == setup.id).order_by(Ending.order))
        ).all()
        rule_items = {e.name: await _ending_rule_items(db, e) for e in endings}

        print("## 엔딩 규칙 순서(DB 재구성 결과)\n")
        for name, items in rule_items.items():
            parts = [
                f"[{str(i.stat_id)[:8]} {i.operator.name} {fmt(i.threshold)} → {i.next_op.name if i.next_op else 'NULL'}]"
                for i in items
            ]  # type: ignore[union-attr]
            print(f"- {name}: {' '.join(parts)}")

        print("\n## 엔딩 경계표\n")
        print("열: 상영회까지 / 호감(도희, 유나, 세빈) → 엔딩별 실측(기대와 다르면 ✗)\n")
        names = list(rule_items)
        print("| 상영회까지 | 도희 | 유나 | 세빈 | " + " | ".join(names) + " |")
        print("|" + "---|" * (4 + len(names)))
        affection_cases = [
            (54.0, 54.0, 54.0),
            (55.0, 55.0, 55.0),
            (35.0, 35.0, 35.0),
            (36.0, 36.0, 36.0),
            (55.0, 20.0, 20.0),
            (20.0, 55.0, 35.0),
            (35.0, 35.0, 36.0),
            (54.5, 20.0, 55.5),
        ]
        for cd in (42.0, 7.5, 1.0, 0.5, 0.0):
            for aff in affection_cases:
                stats = {T.COUNTDOWN_STAT: cd, **dict(zip(AFFECTIONS, aff, strict=True))}
                cells = []
                for name in names:
                    got = evaluate_rule_list(rule_items[name], stats)
                    exp = expected_ending(name, stats)
                    cells.append(("참" if got else "거짓") + ("" if got == exp else " ✗"))
                    if got != exp:
                        bad.append(f"엔딩 {name} @ {cd}, {aff}: 실측 {got} 기대 {exp}")
                print(f"| {fmt(cd)} | " + " | ".join(fmt(a) for a in aff) + " | " + " | ".join(cells) + " |")

        notes = (
            await db.scalars(
                select(SituationNote)
                .where(SituationNote.starting_setup_id == setup.id)
                .order_by(SituationNote.order, SituationNote.entity_id)
            )
        ).all()
        name_of = {n.info_text: n.name for n in notes}
        pairs = [(RULE_LIST_ADAPTER.validate_python(n.condition_rules), n.info_text) for n in notes]

        print("\n## 상황 노트 경계표(호감 3종 20 고정)\n")
        print("| 상영회까지 | 실린 노트 | 단계 노트 수 | 기대 단계 | 판정 |")
        print("|---|---|---|---|---|")
        for cd in COUNTDOWNS:
            stats = {T.COUNTDOWN_STAT: cd, **{s: 20.0 for s in AFFECTIONS}}
            loaded = [name_of[t] for t in _situation_note_texts(pairs, stats)]
            stages = [n for n in loaded if n in STAGES]
            ok = stages == [expected_stage(cd)] and len(loaded) == 1
            if not ok:
                bad.append(f"상황 노트 @ {cd}: {loaded}")
            print(
                f"| {fmt(cd)} | {', '.join(loaded) or '(없음)'} | {len(stages)} | {expected_stage(cd)} | {'통과' if ok else '✗'} |"
            )

        print("\n## 호감 노트 경계(상영회까지 20)\n")
        print("| 호감 값(세 명 같음) | 실린 호감 노트 수 | 기대 | 판정 |")
        print("|---|---|---|---|")
        for a in (44.0, 44.5, 45.0):
            stats = {T.COUNTDOWN_STAT: 20.0, **{s: a for s in AFFECTIONS}}
            loaded = [name_of[t] for t in _situation_note_texts(pairs, stats) if name_of[t] not in STAGES]
            exp = 3 if a >= 45 else 0
            ok = len(loaded) == exp
            if not ok:
                bad.append(f"호감 노트 @ {a}: {loaded}")
            print(f"| {fmt(a)} | {len(loaded)} | {exp} | {'통과' if ok else '✗'} |")

        print("\n## 발행 검증(_load_story_publish_draft)\n")
        version = await db.get(ContentVersion, v6_id)
        assert version is not None
        content = await db.get(Content, version.content_id)
        assert content is not None
        try:
            draft = await _load_story_publish_draft(db, content, version)
            print(f"예외 없음 — 빠진 칸 0, 칸 {len(draft.ordered_cells)}개 정렬됨")
        except HTTPException as exc:
            bad.append(f"발행 검증 위반: {exc.detail}")
            print(f"위반: {exc.status_code} {exc.detail}")
        await db.rollback()

    print("\n## 판정\n")
    print("통과" if not bad else "실패:\n" + "\n".join(f"- {b}" for b in bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    asyncio.run(main(uuid.UUID(sys.argv[1])))
