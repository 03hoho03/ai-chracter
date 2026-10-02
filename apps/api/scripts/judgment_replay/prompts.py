"""판정 문안 스냅숏 ↔ 서버 빌더가 받는 `PromptSet`·`PromptSection`.

서버는 레인마다 활성 세트를 DB 에서 읽는다(`load_active_prompt_set`). 리플레이는 DB 대신 그 결과를 JSON 으로 떠 둔
스냅숏(운영 읽기 전용 조회로 만든 파일)을 쓰므로, 같은 행을 세션 없는 ORM 객체로 다시 만들어 서버 빌더에 그대로 넘긴다
— 렌더 규칙(scope 필터·variant·order·conditional)은 빌더가 하므로 여기서 흉내 내지 않는다.

스냅숏 모양: `{"sets": [{lane, id, version, published_at, user_label, story_assistant_label, story_example_label,
character_assistant_label}], "sections": [{prompt_set_id, lane, channel, scope, order, slot, variant, conditional,
body}]}`. 다른 키(조회 출처 등)는 무시한다.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from api.db.models.prompt import PromptSection, PromptSet


@dataclass(frozen=True)
class PromptSnapshot:
    by_lane: dict[str, tuple[PromptSet, list[PromptSection]]]
    # 결과에 남길 렌더 근거 — 어느 세트로 렌더했는지.
    set_ids: dict[str, str]

    def lane(self, lane: str) -> tuple[PromptSet, list[PromptSection]]:
        if lane not in self.by_lane:
            raise KeyError(f"스냅숏에 {lane} 레인 세트가 없다")
        return self.by_lane[lane]


def load_prompt_snapshot(raw: dict[str, Any]) -> PromptSnapshot:
    by_lane: dict[str, tuple[PromptSet, list[PromptSection]]] = {}
    for item in raw["sets"]:
        prompt_set = PromptSet(
            id=uuid.UUID(item["id"]),
            version=item.get("version"),
            status="published",
            lane=item["lane"],
            user_label=item["user_label"],
            story_assistant_label=item["story_assistant_label"],
            story_example_label=item["story_example_label"],
            character_assistant_label=item["character_assistant_label"],
            published_at=datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None,
        )
        sections = [
            PromptSection(
                prompt_set_id=prompt_set.id,
                channel=section["channel"],
                scope=section["scope"],
                order=section["order"],
                slot=section["slot"],
                variant=section["variant"],
                conditional=section["conditional"],
                body=section["body"],
            )
            for section in raw["sections"]
            if section["prompt_set_id"] == item["id"]
        ]
        by_lane[item["lane"]] = (prompt_set, sections)
    return PromptSnapshot(by_lane=by_lane, set_ids={lane: str(s.id) for lane, (s, _) in by_lane.items()})


def read_prompt_snapshot(path: Path) -> PromptSnapshot:
    return load_prompt_snapshot(json.loads(path.read_text(encoding="utf-8")))


def dump_prompt_snapshot(loaded: Sequence[tuple[PromptSet, Sequence[PromptSection]]]) -> dict[str, Any]:
    """`load_active_prompt_set` 결과를 스냅숏 모양으로 — 격리 DB 의 활성 세트로 스냅숏을 만들거나 왕복을 검사할 때."""
    sets = [
        {
            "lane": prompt_set.lane,
            "id": str(prompt_set.id),
            "version": prompt_set.version,
            "published_at": prompt_set.published_at.isoformat() if prompt_set.published_at else None,
            "user_label": prompt_set.user_label,
            "story_assistant_label": prompt_set.story_assistant_label,
            "story_example_label": prompt_set.story_example_label,
            "character_assistant_label": prompt_set.character_assistant_label,
        }
        for prompt_set, _ in loaded
    ]
    sections = [
        {
            "prompt_set_id": str(prompt_set.id),
            "lane": prompt_set.lane,
            "channel": section.channel,
            "scope": section.scope,
            "order": section.order,
            "slot": section.slot,
            "variant": section.variant,
            "conditional": section.conditional,
            "body": section.body,
        }
        for prompt_set, set_sections in loaded
        for section in set_sections
    ]
    return {"sets": sets, "sections": sections}
