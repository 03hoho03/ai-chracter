"""채팅 단계 표와, 그 표에서 나오는 게시 검증의 판정 채널 표.

판정 채널 표는 게시 검증이 Claude·판정 전용 체인에 어떤 채널을 요구할지 정한다. 값이 하나라도 바뀌면 그 체인 게시가
"누락"이나 "남는 채널"로 막히거나, 판정이 읽을 문안 없이 게시된다. 그래서 단계 표에서 도출하더라도 지금 값을 리터럴로 묶어 둔다."""

from api.admin.prompts import _JUDGMENT_CHANNELS_BY_LANE


def test_publish_validation_judgment_channels_are_derived_without_changing_them() -> None:
    assert _JUDGMENT_CHANNELS_BY_LANE == {
        "story": frozenset(
            {
                "stat_rule_judgment",
                "scene_judgment",
                "ending_judgment",
                "image_judgment",
                "memory_summary",
                "memory_episode",
                "memory_fact",
            }
        ),
        "character": frozenset({"image_judgment", "memory_summary", "memory_episode", "memory_fact"}),
        "publish_filter": frozenset(),
        "novel": frozenset(),
        "novel_screen": frozenset(),
    }
