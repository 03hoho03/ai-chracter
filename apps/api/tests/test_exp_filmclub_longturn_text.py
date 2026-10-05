"""실험 스크립트 `experiments/filmclub_longturn/longturn_text.py` — 조감독 응답 한 턴의 글자 규칙.

양성 사례는 스토리 가이드 런 집계가 결함으로 표시했던 실제 응답 꼴에서, 음성 사례는 같은 규칙이 빼라고 적은
꼴에서 가져왔다. 한쪽만 있으면 "항상 참/항상 거짓" 구현도 통과한다.
"""

from experiments.filmclub_longturn import longturn_text as t

STATUS = "```\n장소 | 학생회관 동아리방\n시간 | 화요일 밤\n함께 | 강도희, 민유나\n지금 | 대본 회의\n```"


def test_status_four_items_at_the_end() -> None:
    result = t.status_metrics(f"*도희가 펜을 멈춘다.* 일부러.\n\n{STATUS}\n")

    assert result.present and result.pos_end and result.fmt_ok
    assert result.other_blocks == 0
    assert t.together(result) == {"도희": True, "유나": True, "세빈": False}
    assert t.status_field(result, "시간") == "화요일 밤"


def test_status_with_empty_together_value_breaks_format() -> None:
    # 스토리 가이드 r1 yuna-3 18턴의 꼴 — 혼자 있는 장면에서 `함께` 값이 비었다.
    reply = "혼자다.\n\n```\n장소 | 기숙사 로비\n시간 | 월요일 밤\n함께 | \n지금 | 유나의 답장 확인하기\n```"

    result = t.status_metrics(reply)

    assert result.present and not result.fmt_ok
    assert result.lines[2] == "함께 | "


def test_status_not_at_end_and_last_block_wins() -> None:
    reply = f"```\n메모\n```\n본문\n{STATUS}\n덧붙인 문장"

    result = t.status_metrics(reply)

    assert result.other_blocks == 1
    assert result.fmt_ok and not result.pos_end


def test_no_fenced_block_means_no_status() -> None:
    assert not t.status_metrics("장소 | 동아리방\n시간 | 밤").present


def test_stat_mimic_rules_and_safe_suffix() -> None:
    assert t.mimic_runs("호감 35%") == [("35", 1)]
    assert t.mimic_runs("관계 Lv.3") == [("3", 2)]
    assert t.mimic_runs("상영회까지 12") == [("12", 3)]
    assert t.mimic_runs("함께 | 강도희(52)") == [("52", 4)]
    # 이름 근처라도 시각·학년 같은 단위가 바로 붙으면 스탯 흉내가 아니다.
    assert t.mimic_runs("도희는 3시에 온다") == []
    assert t.mimic_runs("세빈은 2학년이다") == []
    # 스토리 가이드 r2 yuna-3 17턴에서 본문 스탯 흉내로 잡힌 꼴(초는 안전 단위가 아니다).
    assert t.mimic_runs("*도희가 유나를 1초 정도 빤히 본다.*") == [("1", 4)]


def test_status_digits_split_into_mimic_and_other() -> None:
    other = t.status_metrics("본문\n```\n장소 | 학생회관 1층 로비\n시간 | 밤\n함께 | 강도희\n지금 | 대기\n```")
    mimic = t.status_metrics("본문\n```\n장소 | 동아리방\n시간 | 밤\n함께 | 강도희(52)\n지금 | 대기\n```")
    word = t.status_metrics("본문\n```\n장소 | 동아리방\n시간 | 밤\n함께 | 도희(호감 상승)\n지금 | 대기\n```")

    assert other.digit and not other.mimic_status and other.digit_lines == ["장소 | 학생회관 1층 로비"]
    assert mimic.digit and mimic.mimic_status == [("함께 | 강도희(52)", [("52", 4)])]
    assert word.statword and not word.digit


def test_body_mimic_ignores_the_status_block() -> None:
    reply = "*유나가 웃는다* 씬 이(2)부터 맞춰 봐, 유나.\n\n```\n장소 | 1층\n시간 | 밤\n함께 | 유나\n지금 | 리허설\n```"

    assert t.mimic_body(reply) == [("*유나가 웃는다* 씬 이(2)부터 맞춰 봐, 유나.", [("2", 4)])]


def test_speaker_labels() -> None:
    assert t.labels("도희: 앉아.\n[세빈]：네") == ["도희:", "[세빈]："]
    assert t.labels("도희가 말했다: 앉아.") == []


def test_duplicate_eight_words_from_an_example_but_not_from_the_user() -> None:
    example = "*유나가 몸을 기울인다* 그러니까 제일 어렵다는 거지. 대사가 있으면 대사 뒤에 숨기라도 하잖아?"
    reply = "*유나가 웃는다* 그러니까 제일 어렵다는 거지. 대사가 있으면 대사 뒤에 숨잖아."
    sources = {"ex1": example}

    found = t.duplicate_spans(reply, "그냥 물어봐요", sources)
    quoted = t.duplicate_spans(reply, "그러니까 제일 어렵다는 거지 대사가 있으면 대사 뒤에", sources)
    seven = t.duplicate_spans("그러니까 제일 어렵다는 거지. 대사가 있으면 대사 다른 말", "", sources)

    assert found == [{"src": "ex1", "sample": "그러니까 제일 어렵다는 거지 대사가 있으면 대사 뒤에"}]
    assert quoted == []
    assert seven == []


def test_duplicate_ignores_status_blocks() -> None:
    reply = f"전혀 다른 본문이다.\n\n{STATUS}"

    assert t.duplicate_spans(reply, "", {"prev": f"이전 본문.\n\n{STATUS}"}) == []


def test_day_phrases() -> None:
    reply = "사흘 뒤, 편집실. 다음 날 아침에 보자고 했다. 며칠 뒤에 다시. 2일 후. 일주일 뒤.\n\n" + STATUS

    found = [(p["text"], p["days"]) for p in t.day_phrases(reply)]

    assert found == [("사흘 뒤", 3), ("다음 날", 1), ("며칠 뒤", None), ("2일 후", 2), ("일주일 뒤", 7)]
    assert t.day_phrases("하루 종일 찍었다. 오늘 밤.") == []


def test_weekday_and_step() -> None:
    status = t.status_metrics(f"본문\n{STATUS}")

    assert t.weekday(status) == "화"
    assert t.weekday_step("화", "금") == 3
    assert t.weekday_step("토", "월") == 2
    # 7의 배수로 건너뛰면 0 으로 보인다 — 그래서 요일은 보조 근거다.
    assert t.weekday_step("화", "화") == 0
    assert t.weekday_step(None, "화") is None
