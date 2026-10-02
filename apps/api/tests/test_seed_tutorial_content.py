"""튜토리얼 예시 작품 시드(`data/tutorial/`)의 자리와 손으로 쓴 JSON 의 모양을 검사한다.

제작 가이드는 스토리·캐릭터 빌더의 칸을 단계마다 한 작품으로 채워 가며 설명하고, 그 작품이
여기 있는 스토리 하나와 그 메인 히로인 캐릭터 하나다. 이 작품은 다양성 매트릭스(장르당 세 칸,
고정 slug 목록)의 칸이 아니므로 두 가지가 함께 성립해야 한다.

- 매트릭스 검사에는 끼지 않는다 — 매트릭스 폴더에 들어가면 매트릭스 대조가 깨진다.
- 모든 시드에 걸리는 발행·서술 불변식(`test_seed_content_data.py`·`test_seed_dev_content.py`)에는
  낀다 — 그 검사들은 `STORY_DIRS`·`CHARACTER_DIRS`·`load_all_*()` 를 돌므로, 여기서는 그 목록이
  튜토리얼 폴더를 담고 있는지를 본다.

매트릭스 시드는 생성기가 파일을 쓰기 전에 스탯 아이콘·색·범위를 강제하지만 튜토리얼 JSON 은
손으로 쓰므로 그 검사를 아무도 하지 않는다. 그 몫을 아래 튜토리얼 전용 검사가 진다.
"""

import re
from collections import Counter
from pathlib import Path

from api.chat.keyword_notes import match_keyword_notes
from api.db.models.chat import ChatMessage, ChatMessageRole
from api.db.models.story import KeywordNote
from seed_content.images import situational_image_slug
from seed_content.loader import (
    CHARACTER_DIRS,
    CHARACTERS_DIR,
    STORIES_DIR,
    STORY_DIRS,
    TUTORIAL_CHARACTERS_DIR,
    TUTORIAL_STORIES_DIR,
    load_all_characters,
    load_all_stories,
    load_characters,
    load_stories,
)
from seed_content.matrix import load_matrix

TUTORIAL_STORY_SLUGS = ["tutorial-filmclub"]
TUTORIAL_CHARACTER_SLUGS = ["tutorial-filmclub-yuna"]
# `seed_dev.py` 가 샘플 캐릭터 '미아'의 썸네일을 `images/mia.png` 에서 읽는다.
MIA_IMAGE_SLUG = "mia"

REPO_ROOT = Path(__file__).resolve().parents[3]
# 빌더가 고를 수 있는 값의 원본. 복제하지 않고 FE 소스를 그대로 읽어, FE 목록이 바뀌면 이 검사도
# 따라 바뀌게 한다. 그래서 api 워크플로의 경로 필터에 아래 세 파일이 들어 있다 — 없으면 FE 파일만 바뀐
# PR 에서 이 검사가 돌지 않는다. 파일을 옮기면 그 필터도 함께 고친다.
STAT_ICONS_TS = REPO_ROOT / "apps/web/src/entities/chat-room/model/statIcons.ts"
COLOR_PALETTE_TS = REPO_ROOT / "packages/ui/src/lib/color-palette.ts"
STORY_FORM_SCHEMA_TS = REPO_ROOT / "apps/web/src/features/build-story/model/schema.ts"


def _read_all(pattern: str, path: Path) -> list[str]:
    values = re.findall(pattern, path.read_text(encoding="utf-8"))
    assert values, f"{path.name}: 값을 하나도 못 읽었다 — 파일 모양이 바뀌었으면 이 정규식을 고칠 것"
    return values


def _builder_stat_icons() -> set[str]:
    return set(_read_all(r'\{ name: "(\w+)", label: "[^"]*", Icon: \w+ \}', STAT_ICONS_TS))


def _builder_stat_colors() -> set[str]:
    return set(_read_all(r'value: "(oklch\([^"]*\))"', COLOR_PALETTE_TS))


def _builder_min_ending_turn_gate() -> int:
    (value,) = _read_all(r"turnGate: z\.number\(\)\.min\((\d+)", STORY_FORM_SCHEMA_TS)
    return int(value)


def test_tutorial_content_slugs_are_fixed() -> None:
    """제작 가이드가 이 작품을 예시로 인용하고, 로컬 대화 검증 도구는 slug 로 방을 만든다
    (`story_content_id(slug)`). 파일 이름이 바뀌면 콘텐츠 id 가 바뀌어 가이드가 가리키는 작품과
    검증하던 방이 다른 콘텐츠가 되므로 slug 를 고정한다."""
    assert [story.slug for story in load_stories(TUTORIAL_STORIES_DIR)] == TUTORIAL_STORY_SLUGS
    assert [
        character.slug for character in load_characters(TUTORIAL_CHARACTERS_DIR)
    ] == TUTORIAL_CHARACTER_SLUGS


def test_tutorial_content_stays_outside_the_diversity_matrix() -> None:
    """튜토리얼 작품이 매트릭스 폴더에 들어가면 매트릭스 대조와 고정 slug 목록이 깨진다."""
    tutorial = set(TUTORIAL_STORY_SLUGS) | set(TUTORIAL_CHARACTER_SLUGS)

    assert tutorial.isdisjoint(story.slug for story in load_stories())
    assert tutorial.isdisjoint(character.slug for character in load_characters())
    assert tutorial.isdisjoint(slot.slug for slot in load_matrix())


def test_every_seed_invariant_list_covers_the_tutorial_folders() -> None:
    """발행·서술 불변식은 폴더 목록과 합친 로더로 돈다 — 튜토리얼 폴더가 거기서 빠지면 그
    검사들이 튜토리얼 작품을 조용히 건너뛴다."""
    assert STORY_DIRS == (STORIES_DIR, TUTORIAL_STORIES_DIR)
    assert CHARACTER_DIRS == (CHARACTERS_DIR, TUTORIAL_CHARACTERS_DIR)
    assert set(TUTORIAL_STORY_SLUGS) <= {story.slug for story in load_all_stories()}
    assert set(TUTORIAL_CHARACTER_SLUGS) <= {
        character.slug for character in load_all_characters()
    }


def test_seed_slugs_do_not_collide_across_folders() -> None:
    """시드 이미지는 `images/{slug}.png` 로 찾으므로 스토리·캐릭터·장면·미아의 slug 가 하나라도
    겹치면 두 콘텐츠가 같은 그림 파일을 쓴다. 같은 종류끼리 겹치면(두 폴더에 같은 이름의 스토리)
    콘텐츠 id 까지 같아져 나중에 시드된 쪽이 앞의 것을 덮어쓴다. 폴더가 둘이 되면서 파일 시스템이
    더는 이름 중복을 막아 주지 않아 여기서 막는다."""
    characters = load_all_characters()
    slugs = [story.slug for story in load_all_stories()]
    slugs += [character.slug for character in characters]
    slugs += [
        situational_image_slug(character.slug, order)
        for character in characters
        for order in range(len(character.payload.situational_images))
    ]
    slugs.append(MIA_IMAGE_SLUG)

    duplicates = sorted(slug for slug, count in Counter(slugs).items() if count > 1)

    assert not duplicates, f"여러 시드가 같은 slug 를 쓴다: {duplicates}"


def test_tutorial_stat_icons_and_colors_are_builder_choices() -> None:
    """목록 밖 아이콘 이름은 백엔드가 받아 주지만 게이지에 아이콘이 안 그려지고, 목록 밖 색은
    빌더 피커에서 선택된 칸이 없어 운영 빌더로 옮겨 적을 때 같은 값을 고를 수 없다."""
    icons = _builder_stat_icons()
    colors = _builder_stat_colors()

    for story in load_stories(TUTORIAL_STORIES_DIR):
        for setup in story.payload.starting_setups:
            for stat in setup.stat_defs:
                assert stat.icon in icons, f"{story.slug} / {stat.name}: 빌더에 없는 아이콘 {stat.icon!r}"
                assert stat.color in colors, f"{story.slug} / {stat.name}: 빌더 팔레트에 없는 색 {stat.color!r}"


def test_tutorial_stat_initial_values_sit_inside_their_range() -> None:
    """방은 초기값을 클램프 없이 그대로 싣는다 — 범위 밖이면 게이지가 범위를 벗어난 채 시작하고,
    그 스탯이 처음 바뀌는 턴에 클램프로 값이 튀어 대화와 무관하게 움직인 것처럼 보인다."""
    for story in load_stories(TUTORIAL_STORIES_DIR):
        for setup in story.payload.starting_setups:
            for stat in setup.stat_defs:
                assert stat.min_value <= stat.initial_value <= stat.max_value, (
                    f"{story.slug} / {stat.name}: 초기값 {stat.initial_value} 이 "
                    f"범위 {stat.min_value}~{stat.max_value} 밖이다"
                )


def test_tutorial_ending_gates_meet_the_builder_minimum() -> None:
    """운영에는 이 작품을 빌더 폼으로 옮겨 적는다 — 폼이 받는 최소 턴수보다 작은 게이트는 거기서
    처음 막힌다. 백엔드 발행 검증에도 하한이 있지만 폼 하한과 따로 적힌 값이라 폼 쪽을 읽는다."""
    minimum = _builder_min_ending_turn_gate()

    for story in load_stories(TUTORIAL_STORIES_DIR):
        for setup in story.payload.starting_setups:
            for ending in setup.endings:
                assert ending.turn_count_gate >= minimum, (
                    f"{story.slug} / {ending.name}: 최소 턴수 {ending.turn_count_gate} 이 "
                    f"빌더 하한 {minimum} 보다 작다"
                )


def test_tutorial_suggested_replies_load_their_heroine_note_on_the_first_turn() -> None:
    """제작 가이드는 추천 답변을 누르면 첫 턴부터 그 인물의 키워드북 노트가 열린다고 설명한다. 첫 화면이
    여섯 노트의 키워드를 모두 담아 첫 턴에는 상한(5개)이 걸리고 맨 아래 노트가 빠지므로, 노트 순서를
    바꾸다 추천 답변의 인물 노트가 맨 아래로 가면 그 설명이 조용히 거짓이 된다. 실방처럼 첫 화면을 바로
    앞 AI 응답으로 두고 실제 선택 함수를 돌린다. 인물은 노트 이름 칸으로 찾는다."""
    for story in load_stories(TUTORIAL_STORIES_DIR):
        notes = [
            KeywordNote(
                entity_id=note.id,
                starting_setup_id=note.starting_setup_id,
                info_text=note.info_text,
                trigger_keywords=note.trigger_keywords,
                name=note.name,
                order=order,
                exclude_keywords=note.exclude_keywords,
                sticky_turns=note.sticky_turns,
                always_on=note.always_on,
            )
            for order, note in enumerate(story.payload.keyword_notes)
        ]
        for setup in story.payload.starting_setups:
            # 방을 만들 때 첫 화면은 시작상황, 없으면 프롤로그가 AI 메시지로 들어간다.
            opening = ChatMessage(role=ChatMessageRole.ASSISTANT, content=setup.opening_message or setup.prologue)
            for reply in setup.suggested_replies:
                heroine_notes = [note.name for note in notes if note.name and note.name in reply]
                assert heroine_notes, f"{story.slug} / {reply!r}: 이름 칸으로 찾은 인물 노트가 없다"

                selected = [note.name for note in match_keyword_notes(notes, [opening], reply)]

                for name in heroine_notes:
                    assert name in selected, f"{story.slug} / {reply!r}: 첫 턴에 {name} 노트가 빠진다 (실림 {selected})"

                # 가이드는 첫 턴에 빠지는 노트가 맨 아래 태민의 노트 하나뿐이라고 설명한다. "맨 아래 노트"로만
                # 검사하면 장소 노트를 맨 아래로 옮겨도 통과하므로 이름으로 고정한다 — 장소 노트가 빠지면 그
                # 노트에만 있는 사실(편집실 마감 시각 등)을 첫 턴의 AI가 받지 못한다.
                hit = [note.name for note in notes if match_keyword_notes([note], [opening], reply)]
                dropped = [name for name in hit if name not in selected]
                assert dropped == ["태민"], (
                    f"{story.slug} / {reply!r}: 첫 턴에 태민 노트만 빠져야 한다 (빠짐 {dropped})"
                )
