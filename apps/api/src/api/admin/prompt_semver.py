"""프롬프트 체인·섹션 판(`major.minor.patch`) 매기기.

체인은 (레인, 모델) 세트 줄기, 섹션은 채널 하나(그 채널의 모든 행 묶음) 또는 세트의 화자 라벨 넷 묶음(`speaker_labels`)이다.
게시할 때 그 체인에서 판이 가장 큰 세트(기준판)와 섹션 내용을 바이트로 견주어, 바뀐 섹션만 관리자가 고른 단계(기본 patch)로
올리고 체인은 그중 가장 큰 단계로 올린다. 바뀐 섹션이 없는 게시도 체인만 patch 로 올린다. 기준판이 없는 체인(판을 매긴 게시가
하나도 없음)은 체인·섹션 전부 1.0.0 으로 시작한다.

견주는 상대가 지금 활성 세트가 아니라 기준판인 이유: 판을 모르는 옛 이미지가 번호 없이 게시한 세트가 사이에 있어도, 그 세트와
견주면 거기서 바뀐 섹션이 기준판의 번호를 그대로 물려받아 같은 번호가 다른 내용을 가리키게 된다. 기준판과 견주면 그 변경이 다음
게시의 변경으로 셈해진다.

판은 서빙 경로가 읽지 않는 부속 기록이다 — 어느 세트가 활성인지(`published_at` 최신)는 판과 무관하다. 같은 규칙의 사본이
게시 세트를 넣는 문안 마이그레이션에 있으므로(마이그레이션은 앱 코드를 import 하지 않는다), 여기 규칙을 바꾸면 가장 최근 사본과
견주는 동치 테스트가 알린다.
"""

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.prompt import PromptSection, PromptSectionSemver, PromptSet, PromptSetSemver

SemverLevel = Literal["major", "minor", "patch"]
SectionChange = Literal["changed", "added", "removed", "unchanged", "initial"]
Semver = tuple[int, int, int]
# 섹션 이름 → 그 섹션 내용을 비교할 수 있게 펼친 값.
SectionContents = dict[str, tuple[object, ...]]

SPEAKER_LABELS = "speaker_labels"
_LEVEL_RANK: dict[SemverLevel, int] = {"patch": 0, "minor": 1, "major": 2}
_LEVELS: dict[str, SemverLevel] = {level: level for level in _LEVEL_RANK}


class SectionRow(Protocol):
    @property
    def channel(self) -> str: ...
    @property
    def scope(self) -> str: ...
    @property
    def slot(self) -> str: ...
    @property
    def variant(self) -> str: ...
    @property
    def body(self) -> str: ...
    @property
    def conditional(self) -> bool: ...
    @property
    def order(self) -> int: ...


class LabelSource(Protocol):
    @property
    def user_label(self) -> str: ...
    @property
    def story_assistant_label(self) -> str: ...
    @property
    def story_example_label(self) -> str: ...
    @property
    def character_assistant_label(self) -> str: ...


class SemverLevelError(Exception):
    """바뀌지 않았거나 없는 섹션에 단계를 골랐다 — 화면이 본 차이와 서버가 본 차이가 어긋났다는 신호라 조용히 버리지 않는다."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(names)
        self.names = names


@dataclass(frozen=True)
class ChainBase:
    """기준판과, 판을 계산하는 데 필요한 그 체인의 번호들."""

    set_id: uuid.UUID
    number: Semver
    section_numbers: dict[str, Semver]
    contents: SectionContents
    # 그 체인에서 섹션마다 가장 큰 번호 — 기준판에서 빠졌다가 다시 들어온 섹션이 옛 번호를 다른 내용으로 다시 쓰지 않게 한다.
    section_maxima: dict[str, Semver]


@dataclass(frozen=True)
class SemverPlan:
    number: Semver
    level: SemverLevel | None
    base_set_id: uuid.UUID | None
    sections: dict[str, tuple[Semver, SemverLevel | None]]
    removed: list[str]


def format_semver(number: Semver) -> str:
    return ".".join(str(part) for part in number)


def bump(number: Semver, level: SemverLevel) -> Semver:
    major, minor, patch = number
    if level == "major":
        return (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def chain_level(levels: Iterable[SemverLevel]) -> SemverLevel:
    """바뀐 섹션 단계 중 가장 큰 것. 바뀐 섹션이 없는 게시는 체인만 patch 로 올린다."""
    return max(levels, key=_LEVEL_RANK.__getitem__, default="patch")


def section_contents(labels: LabelSource, sections: Iterable[SectionRow]) -> SectionContents:
    """세트의 섹션 내용. 채널은 그 채널 모든 행의 (범위, 슬롯, 변형, 본문, 조건, 순서)를 정렬한 것이고(행을 담은 순서는 보지
    않는다), 본문은 정규화 없이 그대로 견준다 — 서빙 프롬프트가 한 바이트라도 다르면 다른 판이다. 화자 라벨 넷은 생성 프롬프트와
    정지 시퀀스에 실리므로 `speaker_labels` 섹션으로 견준다."""
    rows: dict[str, list[tuple[str, str, str, str, bool, int]]] = {}
    for section in sections:
        rows.setdefault(section.channel, []).append(
            (section.scope, section.slot, section.variant, section.body, section.conditional, section.order)
        )
    contents: SectionContents = {channel: tuple(sorted(items)) for channel, items in rows.items()}
    contents[SPEAKER_LABELS] = (
        labels.user_label,
        labels.story_assistant_label,
        labels.story_example_label,
        labels.character_assistant_label,
    )
    return contents


def diff_sections(contents: SectionContents, base: SectionContents | None) -> dict[str, SectionChange]:
    if base is None:
        return dict.fromkeys(contents, "initial")
    changes: dict[str, SectionChange] = {}
    for channel in sorted(set(contents) | set(base)):
        if channel not in base:
            changes[channel] = "added"
        elif channel not in contents:
            changes[channel] = "removed"
        else:
            changes[channel] = "unchanged" if contents[channel] == base[channel] else "changed"
    return changes


def draft_fingerprint(contents: SectionContents) -> str:
    """초안 내용 해시. 바뀐 섹션 조회가 내주고 게시 요청이 돌려보내, 그 사이 초안이 바뀌었는지 본다."""
    canonical = json.dumps(sorted(contents.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def plan_semver(base: ChainBase | None, contents: SectionContents, levels: Mapping[str, SemverLevel]) -> SemverPlan:
    """새 게시 세트의 체인·섹션 판. 기준판이 없으면 전부 1.0.0 이고 이 세트에 있는 섹션의 단계는 무시한다 — 바뀐 섹션 조회가
    시작판이라 알린 화면이 단계를 보내도 게시가 막히지 않게 한다."""
    if base is None:
        unknown = sorted(set(levels) - set(contents))
        if unknown:
            raise SemverLevelError(unknown)
        return SemverPlan(
            number=(1, 0, 0),
            level=None,
            base_set_id=None,
            sections={channel: ((1, 0, 0), None) for channel in contents},
            removed=[],
        )

    changes = diff_sections(contents, base.contents)
    changed = {channel for channel, change in changes.items() if change != "unchanged"}
    not_changed = sorted(set(levels) - changed)
    if not_changed:
        raise SemverLevelError(not_changed)
    chosen: dict[str, SemverLevel] = {channel: levels.get(channel, "patch") for channel in changed}
    level = chain_level(chosen.values())

    sections: dict[str, tuple[Semver, SemverLevel | None]] = {}
    for channel in contents:
        if channel not in changed:
            sections[channel] = (base.section_numbers[channel], None)
        elif channel in base.section_maxima:
            sections[channel] = (bump(base.section_maxima[channel], chosen[channel]), chosen[channel])
        else:
            sections[channel] = ((1, 0, 0), chosen[channel])
    return SemverPlan(
        number=bump(base.number, level),
        level=level,
        base_set_id=base.set_id,
        sections=sections,
        removed=sorted(channel for channel, change in changes.items() if change == "removed"),
    )


async def _contents_of(db: AsyncSession, prompt_set: PromptSet) -> SectionContents:
    sections = (
        await db.scalars(select(PromptSection).where(PromptSection.prompt_set_id == prompt_set.id))
    ).all()
    return section_contents(prompt_set, sections)


async def load_base(db: AsyncSession, lane: str, model: str) -> ChainBase | None:
    """(레인, 모델) 체인의 기준판 — 판이 가장 큰 세트. 판을 매긴 세트가 없으면 None."""
    row = await db.scalar(
        select(PromptSetSemver)
        .where(PromptSetSemver.lane == lane, PromptSetSemver.model == model)
        .order_by(PromptSetSemver.major.desc(), PromptSetSemver.minor.desc(), PromptSetSemver.patch.desc())
        .limit(1)
    )
    if row is None:
        return None
    base_set = await db.get(PromptSet, row.prompt_set_id)
    assert base_set is not None  # 판 행의 세트 FK
    section_numbers = {
        section.channel: (section.major, section.minor, section.patch)
        for section in (
            await db.scalars(select(PromptSectionSemver).where(PromptSectionSemver.prompt_set_id == row.prompt_set_id))
        ).all()
    }
    maxima = (
        await db.execute(
            select(
                PromptSectionSemver.channel,
                PromptSectionSemver.major,
                PromptSectionSemver.minor,
                PromptSectionSemver.patch,
            )
            .join(PromptSetSemver, PromptSetSemver.prompt_set_id == PromptSectionSemver.prompt_set_id)
            .where(PromptSetSemver.lane == lane, PromptSetSemver.model == model)
            .distinct(PromptSectionSemver.channel)
            .order_by(
                PromptSectionSemver.channel,
                PromptSectionSemver.major.desc(),
                PromptSectionSemver.minor.desc(),
                PromptSectionSemver.patch.desc(),
            )
        )
    ).all()
    return ChainBase(
        set_id=row.prompt_set_id,
        number=(row.major, row.minor, row.patch),
        section_numbers=section_numbers,
        contents=await _contents_of(db, base_set),
        section_maxima={channel: (major, minor, patch) for channel, major, minor, patch in maxima},
    )


async def write_semver(
    db: AsyncSession, *, prompt_set_id: uuid.UUID, lane: str, model: str, plan: SemverPlan
) -> None:
    """판 행을 넣는다(커밋하지 않는다). 같은 기준판을 읽은 다른 게시가 먼저 커밋했으면 flush 가 `IntegrityError` 다."""
    major, minor, patch = plan.number
    db.add(
        PromptSetSemver(
            prompt_set_id=prompt_set_id,
            lane=lane,
            model=model,
            major=major,
            minor=minor,
            patch=patch,
            level=plan.level,
            base_set_id=plan.base_set_id,
        )
    )
    for channel, ((section_major, section_minor, section_patch), level) in plan.sections.items():
        db.add(
            PromptSectionSemver(
                prompt_set_id=prompt_set_id,
                channel=channel,
                major=section_major,
                minor=section_minor,
                patch=section_patch,
                level=level,
            )
        )
    await db.flush()


async def assign_semver(
    db: AsyncSession, *, set_id: uuid.UUID, levels: Mapping[str, SemverLevel] | None = None
) -> SemverPlan:
    """이미 넣은 게시 세트에 판을 매긴다 — 문안 마이그레이션의 판 매기기 블록과 같은 일을 하는 앱 쪽 짝이다."""
    prompt_set = await db.get(PromptSet, set_id)
    assert prompt_set is not None
    base = await load_base(db, prompt_set.lane, prompt_set.model)
    plan = plan_semver(base, await _contents_of(db, prompt_set), levels or {})
    await write_semver(db, prompt_set_id=set_id, lane=prompt_set.lane, model=prompt_set.model, plan=plan)
    return plan


async def semvers_of(db: AsyncSession, set_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = (await db.scalars(select(PromptSetSemver).where(PromptSetSemver.prompt_set_id.in_(list(set_ids))))).all()
    return {row.prompt_set_id: format_semver((row.major, row.minor, row.patch)) for row in rows}


async def section_semvers_of(db: AsyncSession, set_id: uuid.UUID) -> list[tuple[str, Semver, SemverLevel | None]]:
    rows = (
        await db.scalars(
            select(PromptSectionSemver)
            .where(PromptSectionSemver.prompt_set_id == set_id)
            .order_by(PromptSectionSemver.channel)
        )
    ).all()
    # 단계 값은 CHECK 제약이 셋으로 묶어 둔다.
    return [
        (row.channel, (row.major, row.minor, row.patch), _LEVELS[row.level] if row.level is not None else None)
        for row in rows
    ]
