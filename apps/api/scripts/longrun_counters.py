"""긴 턴 런의 신규 L0 카운터 — 인물 이름 라벨 누출과 수치 노출의 **후보**를 뽑는다.

    uv run python scripts/longrun_counters.py <runDir> <slug> [<slug> ...]

`longrun_bins.py` 가 만든 `<runDir>/analysis/bins/<slug>__<구간>.json` 을 읽어 후보를 JSON 으로 낸다.
기존 분석기(`analyze_chat_probe.py`)는 고치지 않고 이 모듈을 따로 둔다(chat-longrun-goal-prompt.md LB-24).
여기서 나온 것은 **후보**다 — 확정은 사람이 원문을 읽고 한다(§7-3). 후보 수를 결함 수로 보고하지 않는다.

- 인물 이름 라벨: 사전 등록 식 `(^|\\n)\\s*(<이름>)\\s*:` 그대로. 이름은 시드 settingText 에서 뽑았고
  (`NAMES`), 실행할 때 그 이름이 settingText 에 실제로 있는지 확인한다(추출 근거가 코드와 어긋나면 멈춘다).
  시드에 없는, 모델이 지어낸 이름도 놓치지 않으려고 줄머리 한글 2~4자 + 콜론을 **보조 후보**로 함께 낸다.
- 수치 노출: 스탯 이름 앞뒤 10자 안의 아라비아 숫자, 또는 스탯 단위(`%·점·도·시간·성·일`)가 붙은 숫자.
  3편 settingText 가 수치 노출을 금지하지 않았으므로 결함이 아니라 **관측**이다(§2-6·§7-3).
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

_SEED_DIR = Path(__file__).parent / "seed_content" / "data" / "stories"

# 시드 settingText 에 이름으로 나오는 인물(2026-09-24 settingText 통독). 따옴표 안 문구는 근거 원문.
# comedy: 「상주인 박철민과 눈치 빠른 부의함 접수대 친척들」 — 친척·조문객은 이름이 없다.
# healing: 「가장 핵심적인 인물인 '정하나'는 28세 여성으로」 — 다른 손님은 이름이 없다.
# wuxia: 「등장인물인 단운혁은 스승을 참살한 냉혹한 검객으로」 — 멸절검선은 초식 이름이다.
NAMES: dict[str, tuple[str, ...]] = {
    "comedy-condolence": ("박철민",),
    "healing-4am": ("정하나",),
    "wuxia-oneform": ("단운혁",),
}

_UNITS = ("%", "점", "도", "시간", "성", "일")
# 단위는 긴 것부터 — `시간` 이 `시` 로 끊기지 않게.
_UNIT_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:%|시간|점|도|성|일)")
_DIGIT = re.compile(r"\d")
_GENERIC_LABEL = re.compile(r"(^|\n)[\s(\[\"“'*]*([가-힣]{2,4})\s*:")
_STAT_WINDOW = 10
_CONTEXT = 30


def _seed(slug: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_SEED_DIR / f"{slug}.json").read_text(encoding="utf-8"))
    return data


def _name_label(names: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(^|\n)\s*(" + "|".join(map(re.escape, names)) + r")\s*:")


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(0, start - _CONTEXT) : end + _CONTEXT].replace("\n", "⏎")


def candidates(text: str, names: tuple[str, ...], stat_names: list[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for match in _name_label(names).finditer(text):
        found.append({"kind": "name_label", "match": match.group(2),
                      "context": _snippet(text, match.start(2), match.end())})
    for match in _GENERIC_LABEL.finditer(text):
        if match.group(2) in names:
            continue
        found.append({"kind": "generic_label", "match": match.group(2),
                      "context": _snippet(text, match.start(2), match.end())})
    for match in _UNIT_NUMBER.finditer(text):
        found.append({"kind": "unit_number", "match": match.group(),
                      "context": _snippet(text, match.start(), match.end())})
    for stat in stat_names:
        for match in re.finditer(re.escape(stat), text):
            window = text[max(0, match.start() - _STAT_WINDOW) : match.end() + _STAT_WINDOW]
            if _DIGIT.search(window):
                found.append({"kind": "stat_near_number", "match": stat,
                              "context": _snippet(text, match.start(), match.end())})
    return found


def scan(run_dir: Path, slug: str) -> dict[str, Any]:
    seed = _seed(slug)
    setting = str(seed["settingText"])
    names = NAMES[slug]
    missing = [name for name in names if name not in setting]
    if missing:
        raise SystemExit(f"{slug}: settingText 에 없는 이름 {missing} — NAMES 근거가 틀렸다")
    stat_names = [str(stat["name"]) for stat in seed["startingSetups"][0]["statDefs"]]

    bins: list[dict[str, Any]] = []
    for path in sorted((run_dir / "analysis" / "bins").glob(f"{slug}__*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entry: dict[str, Any] = {"bin": data["bin"], "observed": data["observed"], "hits": []}
        for result in data["results"]:
            replies = [item["text"] for item in result["transcript"][1:] if item["role"] == "진행자"]
            for turn, reply in zip(result["turns"], replies, strict=True):
                for hit in candidates(reply, names, stat_names):
                    entry["hits"].append({"turn": turn, **hit})
        bins.append(entry)
    return {"slug": slug, "names": list(names), "statNames": stat_names,
            "units": list(_UNITS), "bins": bins}


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    run_dir = Path(sys.argv[1])
    print(json.dumps([scan(run_dir, slug) for slug in sys.argv[2:]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
