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
from generate_seed_stories import NARRATOR_WORDS, stat_display_name
from seed_content.loader import CHARACTERS_DIR, STORIES_DIR, load_characters, load_stories
from seed_content.matrix import load_matrix
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


def test_every_seed_story_keeps_its_matrix_concept() -> None:
    """생성기는 본문만 채운다 — 제목/한줄/타겟/장르/스탯 이름은 §7 슬롯 그대로여야 한다.

    LLM 이 콘셉트를 바꿔버리면 다양성 매트릭스가 보장하던 좌표 분산이 조용히 무너지므로,
    배치가 늘어날 때마다(US-015~019) 이 대조를 사람이 다시 하지 않도록 여기서 고정한다.
    """
    slots = {slot.slug: slot for slot in load_matrix()}

    for story in load_stories():
        slot = slots.get(story.slug)
        assert slot is not None, f"{story.slug}: 다양성 매트릭스에 없는 slug 다"

        payload = story.payload
        assert payload.name == slot.title, f"{story.slug}: 제목이 §7 과 다르다"
        assert payload.one_liner == slot.one_liner, f"{story.slug}: 한 줄 소개가 §7 과 다르다"
        assert payload.genre_id == slot.genre_id, f"{story.slug}: 장르가 §7 과 다르다"
        assert payload.target is not None and payload.target.value == slot.target, (
            f"{story.slug}: target 이 §7 과 다르다"
        )
        assert len(payload.starting_setups) == len(slot.starting_setups), (
            f"{story.slug}: 시작 상황 개수가 §7 과 다르다"
        )

        expected_stats = sorted(stat_display_name(stat) for stat in slot.stats)
        for setup in payload.starting_setups:
            assert sorted(stat.name for stat in setup.stat_defs) == expected_stats, (
                f"{story.slug} / {setup.name}: 스탯 이름이 §7 과 다르다"
            )


def test_every_seed_story_setting_text_instructs_the_narrator() -> None:
    """`settingText` 는 런타임에 서술자의 지시문으로 들어간다 — 사용자용 소개문이면 화자가 뒤집힌다."""
    for story in load_stories():
        setting_text = story.payload.setting_text or ""
        assert any(word in setting_text for word in NARRATOR_WORDS), (
            f"{story.slug}: settingText 가 서술자에게 주는 지시문이 아니다"
        )


def test_no_seed_content_file_contains_escaped_newlines() -> None:
    r"""`\n` 두 글자가 그대로 저장되면 화면에도 프롬프트에도 글자로 보인다.

    JSON 파싱도 발행 검증도 통과하는 종류의 결함이라(US-015 실측) 파일 원문에서 직접 본다.
    진짜 줄바꿈은 `"\n"` 으로 인코딩되므로 여기 걸리는 건 백슬래시 자체가 저장된 경우뿐이다.
    """
    for path in sorted(STORIES_DIR.glob("*.json")) + sorted(CHARACTERS_DIR.glob("*.json")):
        assert "\\\\n" not in path.read_text(encoding="utf-8"), (
            f"{path.name}: 줄바꿈이 이스케이프 시퀀스 글자 그대로 저장돼 있다"
        )


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


def test_seed_story_ending_thresholds_are_reachable_but_not_free() -> None:
    """엔딩 규칙이 스탯 범위 안이면서, 초기값 그대로는 만족되지 않아야 한다.

    범위 밖 임계값은 영영 안 열리고, 반대로 초기값에서 이미 참인 규칙은 스탯을 장식으로
    만든다(턴게이트만 넘으면 판정 프롬프트 하나로 엔딩이 난다). 둘 다 실제로 채팅을
    해보기 전에는 드러나지 않으므로 여기서 막는다. 생성기(US-013)도 파일로 쓰기 전에 같은
    검사를 하지만, 그건 생성 시점 한 번뿐이라 커밋된 파일은 여기서 다시 본다.
    """
    for story in load_stories():
        for setup in story.payload.starting_setups:
            stats = {stat.id: stat for stat in setup.stat_defs}
            initial_values = {str(stat.id): float(stat.initial_value) for stat in setup.stat_defs}
            for ending in setup.endings:
                for item in ending.stat_rules:
                    rules = item.rules if isinstance(item, EndingRuleGroupDraftItem) else [item]
                    for rule in rules:
                        stat = stats[rule.stat_id]
                        assert stat.min_value <= rule.threshold <= stat.max_value, (
                            f"{story.slug} / {ending.name}: "
                            f"{stat.name} 임계값 {rule.threshold} 이 범위 밖이다"
                        )
                rule_items = [_preview_ending_rule_list_item(item) for item in ending.stat_rules]
                assert not evaluate_rule_list(rule_items, initial_values), (
                    f"{story.slug} / {ending.name}: 스탯이 하나도 안 움직여도 규칙이 만족된다"
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


def test_seed_story_development_examples_read_as_a_turn_transcript() -> None:
    """`developmentExample` 은 문체·구조·소품을 준-축자 복제시키는 템플릿 씨앗이라(US-021 실측)
    포맷 자체가 그대로 학습된다.

    - 화자 라벨이 문단 중간에 인라인으로 박혀 있으면(줄바꿈 없이 턴이 이어붙은 경우) 모델이
      자기 응답 안에 `사용자:` 를 그대로 찍는다 — 30 개 `settingText` 가 하나같이 "응답 앞에
      라벨을 붙이지 마라"고 지시하는 것과 정면으로 어긋나는 신호다.
    - 예시가 사용자 턴으로 끝나면 모델이 사용자의 대사까지 대신 써버린다(화자 뒤집힘).
    런타임 프롬프트(`build_story_generation_prompt`)가 대화 기록을 같은 `화자: 내용` 줄
    형식으로 넣으므로, 라벨을 줄 맨 앞에 두는 것 자체는 오히려 일관된다.
    """
    narrator_labels = {"서술자", "진행자"}

    for story in load_stories():
        example = story.payload.development_example
        if not example:
            continue

        turns = []
        for line in example.split("\n"):
            speaker, separator, _ = line.partition(":")
            speaker = speaker.strip()
            if separator and speaker in narrator_labels | {"사용자"}:
                turns.append(speaker)
                continue
            for label in narrator_labels | {"사용자"}:
                assert f"{label}:" not in line, (
                    f"{story.slug}: 화자 라벨 '{label}:' 이 줄 중간에 박혀 있다 — 턴마다 줄을 나눌 것"
                )

        assert turns, f"{story.slug}: developmentExample 에 화자 라벨이 하나도 없어 턴 구분이 안 된다"
        assert turns[-1] in narrator_labels, (
            f"{story.slug}: developmentExample 이 사용자 턴으로 끝난다 — 모델이 사용자 대사를 대신 쓴다"
        )


def test_seed_story_setting_text_does_not_quote_stat_names() -> None:
    """스탯 증감·엔딩 조건은 `settingText` 가 아니라 스탯 `description` 의 몫이다.

    별도 판정 호출(`build_stat_judgment_prompt`)이 `description` 만 보고 판단하므로,
    `settingText` 에 적힌 규칙은 판정에 반영되지도 않으면서 서술자 지시문만 오염시킨다
    (healing-walkinglog 가 실제로 이랬다). 규칙은 스탯 이름을 따옴표로 인용하는 형태로
    나타나므로 그 패턴을 금지선으로 삼는다 — 개념을 산문으로 언급하는 것은 막지 않는다.
    """
    for story in load_stories():
        setting_text = story.payload.setting_text or ""
        for setup in story.payload.starting_setups:
            for stat in setup.stat_defs:
                for quoted in (f"'{stat.name}'", f'"{stat.name}"', f"“{stat.name}”"):
                    assert quoted not in setting_text, (
                        f"{story.slug}: settingText 가 스탯 {quoted} 을 인용해 규칙처럼 적고 있다 "
                        f"— 스탯 description 으로 옮길 것"
                    )
