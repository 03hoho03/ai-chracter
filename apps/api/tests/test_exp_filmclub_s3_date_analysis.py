"""보완판 리플레이 날짜 분석기 — 장면 머리 날수 문구·밤 넘김·날짜 정합을 응답 하나로 본다."""

from experiments.filmclub_longturn import s3_date_analysis as sda

BASE = {
    "previousWeekday": "수",
    "previousTime": "수요일 저녁",
    "bodyBase": "2025-09-24",
    "chainBase": "2025-09-24",
}


def _reply(body: str, time: str) -> str:
    return f"{body}\n\n```\n장소 | 동아리방\n시간 | {time}\n함께 | 강도희\n지금 | 회의\n```"


def test_scene_head_phrase_counts_and_dialogue_phrase_is_left_for_reading() -> None:
    read = sda.read_reply(
        _reply("*세빈이 손을 흔든다.*\n\n*다음 날, 동아리방.* 며칠 뒤에 보자더니 벌써 왔네.", "9월 25일 목요일 낮"),
        22,
        BASE,
    )
    assert read["leadPhrases"] == ["다음 날"] and read["otherPhrases"] == ["며칠 뒤"]
    assert read["moved"] and not read["unmarkedMove"] and not read["saheul"] and not read["defects"]
    assert read["date"]["weekdayMatches"] and read["date"]["matchesBody"] and not read["date"]["exampleCopy"]


def test_same_weekday_going_back_in_the_day_is_an_unmarked_overnight_move() -> None:
    read = sda.read_reply(_reply("*알람이 울린다.*", "수요일 아침"), 105, BASE)
    assert read["weekdayStep"] == 1 and read["unmarkedMove"] and read["date"] is None


def test_wrong_calendar_weekday_copied_example_date_and_stray_digit_are_caught() -> None:
    read = sda.read_reply(_reply("*사흘 뒤.*", "9월 30일 목요일 밤 3시"), 22, BASE)
    assert read["saheul"] and read["leadDays"] == 3
    assert not read["date"]["weekdayMatches"] and read["date"]["exampleCopy"]
    assert read["defects"] == ["날짜 밖 숫자"]
