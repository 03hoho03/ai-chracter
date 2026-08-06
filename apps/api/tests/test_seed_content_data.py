"""리포에 커밋된 시드 콘텐츠 데이터 파일 자체를 검사한다 (US-008 이후).

`test_seed_content.py` 가 로더의 **동작**을 인위적인 payload 로 검사한다면, 이 파일은
`data/characters/*.json` / `data/stories/*.json` **실물**이 발행 가능한 상태인지를 본다 —
시드를 돌리거나 DB 를 띄우지 않고도 "이 JSON 은 홈 목록에 뜰 수 있다"가 보장된다.

썸네일 자산만은 시드 실행 시점에 만들어져 호출부가 payload 에 주입하므로(`ensure_asset`,
US-003/005), 검증 전에 자리표시자 UUID 를 채워 넣는다.
"""

import uuid

from api.chat.ending_rules import evaluate_rule_list
from api.chat.router import _preview_ending_rule_list_item
from api.content.publish import validate_character_publish
from api.content.schemas import EndingRuleGroupDraftItem
from api.db.models.character import CharacterVersionDetail
from api.db.models.content import Content, ContentVersion
from seed_content.loader import load_characters, load_stories
from seed_content.upsert import _validate_payload

MAJOR_CHARACTER_SLUG = "romance-3rdloop-dj"
MAJOR_STORY_SLUG = "romance-3rdloop"
ROMANCE_GENRE_ID = uuid.UUID("b8a1e6b0-1c1a-4b8a-9b0a-000000000001")


def test_every_seed_character_passes_publish_validation() -> None:
    characters = load_characters()
    assert characters, "시드 캐릭터가 하나도 없다"

    for character in characters:
        payload = character.payload
        missing = validate_character_publish(
            Content(genre_id=payload.genre_id, target=payload.target),
            ContentVersion(detail_description=payload.description),
            CharacterVersionDetail(
                name=payload.name,
                one_liner=payload.one_liner,
                thumbnail_asset_id=uuid.uuid4(),  # 시드가 실행 시점에 채운다
                intro=payload.intro,
                character_prompt=payload.character_prompt,
            ),
        )
        assert missing == [], f"{character.slug}: 발행 검증 실패 — {missing}"


def test_every_seed_story_passes_publish_validation() -> None:
    """`upsert_story` 가 실제로 거는 관문(발행 검증 + 어긋난 스탯 참조)을 그대로 통과해야 한다."""
    stories = load_stories()
    assert stories, "시드 스토리가 하나도 없다"

    for story in stories:
        payload = story.payload.model_copy(
            update={"thumbnail_asset_id": uuid.uuid4()}  # 시드가 실행 시점에 채운다
        )
        assert _validate_payload(payload) == [], f"{story.slug}: 발행 검증 실패"


def test_major_story_matches_the_fixed_concept() -> None:
    """§7 R1 의 확정 콘셉트(제목/타겟/시작상황 2개/스탯 3종)에서 벗어나면 안 된다."""
    payload = next(
        story.payload for story in load_stories() if story.slug == MAJOR_STORY_SLUG
    )

    assert payload.name == "3회차 청취자, 이번엔 그를 살린다"
    assert payload.genre_id == ROMANCE_GENRE_ID
    assert payload.target is not None and payload.target.value == "female"
    assert len(payload.starting_setups) == 2
    assert len(payload.keyword_notes) >= 4
    assert len(payload.shortcuts) == 2

    for setup in payload.starting_setups:
        assert [stat.name for stat in setup.stat_defs] == ["신뢰", "집착도", "남은 방송 회차"]
        assert len(setup.endings) >= 2
        for stat in setup.stat_defs:
            assert stat.min_value <= stat.initial_value <= stat.max_value
            assert stat.icon and stat.color and stat.description
        for ending in setup.endings:
            assert ending.turn_count_gate >= 10
            assert ending.judgment_prompt.strip()


def test_major_story_ending_thresholds_are_reachable_but_not_free() -> None:
    """엔딩 규칙이 스탯 범위 안이면서, 초기값 그대로는 만족되지 않아야 한다.

    범위 밖 임계값은 영영 안 열리고, 반대로 초기값에서 이미 참인 규칙은 스탯을 장식으로
    만든다(턴게이트만 넘으면 판정 프롬프트 하나로 엔딩이 난다). 둘 다 실제로 채팅을
    해보기 전에는 드러나지 않으므로 여기서 막는다.
    """
    payload = next(story.payload for story in load_stories() if story.slug == MAJOR_STORY_SLUG)

    for setup in payload.starting_setups:
        stats = {stat.id: stat for stat in setup.stat_defs}
        initial_values = {str(stat.id): float(stat.initial_value) for stat in setup.stat_defs}
        for ending in setup.endings:
            for item in ending.stat_rules:
                rules = item.rules if isinstance(item, EndingRuleGroupDraftItem) else [item]
                for rule in rules:
                    stat = stats[rule.stat_id]
                    assert stat.min_value <= rule.threshold <= stat.max_value, (
                        f"{ending.name}: {stat.name} 임계값 {rule.threshold} 이 범위 밖이다"
                    )
            rule_items = [_preview_ending_rule_list_item(item) for item in ending.stat_rules]
            assert not evaluate_rule_list(rule_items, initial_values), (
                f"{ending.name}: 스탯이 하나도 안 움직여도 규칙이 만족된다"
            )


def test_major_character_is_written_for_the_generated_images() -> None:
    """메이저 캐릭터는 상황 이미지 4장과 1:1 로 맞물려야 한다.

    배열 위치가 곧 `situational_image_slug()` 의 scene 번호이자 매칭 우선순위(`order`)라,
    개수가 바뀌면 PNG 가 엇갈리고 순서가 바뀌면 우선순위가 뒤집힌다.
    """
    payload = next(
        character.payload
        for character in load_characters()
        if character.slug == MAJOR_CHARACTER_SLUG
    )

    assert len(payload.situational_images) == 4
    assert len(payload.example_dialogues) >= 2
    assert payload.genre_id == ROMANCE_GENRE_ID
    assert payload.target is not None and payload.target.value == "female"

    conditions = [image.trigger_condition for image in payload.situational_images]
    assert len(set(conditions)) == 4
    assert all(condition.strip() for condition in conditions)
