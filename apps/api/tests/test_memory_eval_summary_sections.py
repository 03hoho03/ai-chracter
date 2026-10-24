"""요약 본문의 칸별 글자 수·비율 — 줄 맨 앞 머리글로만 나누고, 머리글 앞 글·지시문에 없는 칸 이름을 따로 센다."""

import json
from pathlib import Path

from memory_eval.summary_sections import NO_HEADER, section_chars, section_report, summaries_from_file


def test_sections_split_on_line_start_headers_and_count_the_stripped_body() -> None:
    summary = "[지금] 금요일 저녁.\n\n[관계] 민지는 [지금] 화가 났다.\n태민은 믿는다.\n[지난 일] 상영회."
    assert section_chars(summary) == {
        "지금": len("금요일 저녁."),
        "관계": len("민지는 [지금] 화가 났다.\n태민은 믿는다."),
        "지난 일": len("상영회."),
    }


def test_a_known_header_right_after_a_sentence_end_on_the_same_line_starts_a_section() -> None:
    # 요약이 세 칸을 한 줄에 이어 쓰기도 한다. 문장 끝 뒤가 아닌 자리의 머리글 꼴 글은 본문이다.
    summary = "[지금] 금요일. [관계] 민지는 [지금] 화가 났다! [지난 일] 상영회. [다른 칸] 가"
    assert section_chars(summary) == {
        "지금": len("금요일."),
        "관계": len("민지는 [지금] 화가 났다!"),
        "지난 일": len("상영회. [다른 칸] 가"),
    }


def test_report_ratios_use_all_section_characters_and_flag_unknown_headers() -> None:
    report = section_report("머리 글\n[지금] 가나\n[관계] 가나다라마바\n[비밀] 가나")
    assert report["total"] == len("머리 글") + 2 + 6 + 2
    assert report["sections"][NO_HEADER]["chars"] == len("머리 글")
    assert report["relationRatio"] == 6 / report["total"]
    assert report["unknownHeaders"] == ["비밀"]


def test_a_summary_without_a_relation_section_reports_zero_relation_ratio() -> None:
    assert section_report("[지금] 가\n[지난 일] 나")["relationRatio"] == 0.0
    assert section_report("")["relationRatio"] is None


def test_driver_memory_log_gives_the_first_memory_snapshot_summary(tmp_path: Path) -> None:
    log = tmp_path / "memory-snapshots.jsonl"
    rows = [
        {"kind": "roomStatic"},
        {"kind": "memorySnapshot", "summary": "[관계] 첫 요약"},
        {"kind": "memorySnapshot", "summary": "[관계] 프로브 뒤 요약"},
    ]
    log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    assert summaries_from_file(log) == [(str(log), "[관계] 첫 요약")]
    plain = tmp_path / "summary.txt"
    plain.write_text("[지금] 본문", encoding="utf-8")
    assert summaries_from_file(plain) == [(str(plain), "[지금] 본문")]
