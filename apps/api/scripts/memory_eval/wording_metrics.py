"""묶음 1 문안 시제품 지표 — 목적함수 파일의 `summarySlot`·`factsKnownBy` 기준을 개발 문항으로만 센다. 내보내는 것은 개수·비율과
이름표(판·작품·체크포인트)뿐이다. 요약 본문·사실 값·문항 id 는 내보내지 않는다 — 문안을 고치는 다음 단계가 받는 것이 이 숫자다.

개발 한정: 심기 표는 분할 폴더의 개발 보기(`holdout.load_view`, 시험 정답 파일을 열지 않는다)로만 읽고, 받은 보기에 개발이
아닌 문항이 하나라도 있으면 거부한다. 문항을 좁혀 셀 때 시험 id 를 주면 그 보기가 거부한다.

문항을 셀 체크포인트 = 그 문항을 묻는 체크포인트 가운데 심은 턴이 모두 접힌 것(`probeCheckpoints.offline`). 그 체크포인트의
요약은 결과 머리 줄이 적은 그 체크포인트 스냅샷 수 번째 접기의 요약이고, 사실 행은 그 번째 스냅샷까지의 행이다.

글 맞추기는 모두 사실 키와 같은 정규화(NFC·casefold·공백 하나) 뒤 부분 문자열이다. 사람 이름은 전체 이름과, 세 글자 한글
이름이면 성을 뗀 두 글자도 같은 사람으로 본다.

요약(한 편을 문장·줄 단위 마디로 나눠 본다. 줄 머리 `-` 목록 항목은 문장이 여럿이어도 한 마디다):
- 비밀 내용 단서 = 그 비밀의 누출 단서 묶음 낱말 + 심기 키워드. 마디가 내용을 담았다 = 단서가 둘 이상, 또는 단서 하나와 주인·
  아는 인물 이름이 함께 있다.
- 표기 = "…만 앎/안다/알/아는/압니다" 꼴의 아는 사람 표기. 마침표 뒤에 띄어 붙인 괄호는 앞 마디에 붙여 본다. 표기했다
  (secretMarked) = 표기가 있는 마디가 그 비밀 내용을 담았다 — "누가 누구에게 무엇을 털어놓았다" 꼴도 무엇(단서)과 이름이 함께라
  잡힌다. 주인 이름과 표기만 있는 마디는 그 주인의 어느 비밀인지 가릴 수 없어 세지 않는다.
- 본문 노출(secretBodyExposed) = 표기 밖에 비밀 내용이 드러났다 — 아는 사람 표기가 없는 마디가 그 비밀 내용을 담았다. 표기와
  함께 적힌 내용은 노출로 세지 않는다.
- 관계 보존(relationKept) = 비밀 표기 괄호를 지운 요약에서 두 사람을 함께 부른 마디가 있다. 보조 숫자 relationLatestCue = 그 마디에 마지막 상태 말(정답 앞머리)
  이나 마지막 심기 키워드가 있다.

사실(그 비밀의 행 = 주어·대상·속성·값을 이은 글이 위 "내용을 담았다" 규칙에 맞는 행, 그중 가장 늦은 스냅샷·순서의 행):
- 사용자 이름(아는 사람에서 뺀다) = 실행기가 방 이름 목록에서 뺀 이름(결과 머리 줄)과 같다. 사실 결과는 끝의 완료 표지 줄이
  있어야 센다.
- secretRowFound = 그런 행이 있다. knownByKept = 그 행의 아는 인물(사용자 이름 제외)을 이름으로 맞춘 집합이 기대 집합과 같다(빠져도,
  모르는 인물이 끼어도 아니다). ownerMarked = 그 행의 값에 주인 이름이 있다.
- duplicateKeyRows = 개발 비밀에 맞는 행 가운데 같은 스냅샷에서 같은 사실 키로 한 번 넘게 쓴 행 수(스냅샷 사이의 같은 키는 갱신이라
  세지 않는다).

미확인 주장(정답 사실의 truth_status 가 claimed 인 문항, 범주 무관): 단서는 비밀과 같고, 사람은 그 말을 한 인물(said_by)이다.
말한 사람이 사용자 표기면 사용자 호칭("사용자"·"당신"·머리 줄 userNames) 가운데 하나를 그 사람 이름으로 본다 — 요약·장면이
사용자를 방마다 다르게 부르기 때문이다(요약·장면 모두 같다).
- 요약: claimSourced = 그 주장 내용을 담은 마디에 말한 인물 이름과 출처 말("주장"·"라고 말했다"·"했다고"·"에 따르면"·
  "확인되지" 등. "라고" 홀로는 "…라고 부르는" 같은 호칭이라 세지 않는다)이 함께 있다. claimFactualized = 그 내용을 담았는데 출처 말이 없는 마디가 있다(사실처럼 적었다).

장면(시제품 결과 JSON 의 장면 = 제목 + 본문, 사용자 이름은 결과 옆 .meta.json 의 userNames):
- 혼자 본 비밀(secret·witnessed)과 털어놓은 비밀(secret·confided)마다 Found = 그 내용을 담은 장면이 있다, KnownByKept = 그런 장면 중
  가장 늦은 것의 아는 사람(사용자 제외)을 이름으로 맞춘 집합이 기대 집합과 같다(비면 아니다).
- 서술 둔갑은 인물이 한 미확인 주장만 센다 — 말한 사람이 모두 사용자 호칭이면 사용자 자신이 아는 일이라 서술로 적혀도 인물의
  지식이 오염되지 않는다. claimsCharacter = 그런 인물 주장 문항 수(아래 두 칸의 분모).
- 인물 주장마다 그 내용을 담은 서술(asserted_by narration) 장면을 본다. 본문에 말한 인물 이름과 전언 표지(위 출처 말, 또는
  큰따옴표·낫표 인용)가 함께 있으면 출처를 밝힌 서술, 아니면 출처 없는 서술이다. claimNarrationMixed = 출처 없는 서술 장면이
  하나라도 있는 문항 수 — 안전 쪽 지표라 0 이어야 한다. claimNarrationSourced = 서술 장면이 모두 출처를 밝힌 문항 수(한 문항은
  둘 중 하나로만 센다).
- 확인된 디테일(detail · confirmed)의 내용을 담은 장면 수(detailEpisodes)와 그중 서술 장면 수(detailNarrationEpisodes). 개발
  디테일 문항은 단서가 낱말 하나뿐이라 단서 하나만 있어도 내용을 담은 장면으로 본다(다른 범주는 위 규칙 그대로)."""

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from api.chat.memory_facts import normalize_part

from api.chat.prompt_builder import PromptNames

from memory_eval import holdout
from memory_eval.wording_proto import excluded_user_names
from memory_eval.plants import PlantSet

_MARKER = re.compile(r"만\s*(?:앎|안다|알|아는|압니다)")
_MARKER_PAREN = re.compile(r"\([^()]*만\s*(?:앎|안다|알|아는|압니다)[^()]*\)")
_SENTENCE = re.compile(r"(?<=[.!?。])\s+")
_HANGUL = re.compile(r"^[가-힣]{3}$")
# "라고" 는 뒤에 말하기 말이 붙을 때만 출처다 — 홀로 쓰면 "…라고 부르는" 같은 호칭도 출처로 센다.
_SOURCE = re.compile(
    r"주장|라고\s*(?:주장|말|했|함|한다)|했다고|다고\s*(?:함|했|한다|말)|에\s*따르면|자칭|확인되지|확인\s*안|미확인|말뿐"
)
# 장면 본문의 인용 — 큰따옴표·낫표로 감싼 말. 작은따옴표는 강조에도 써서 넣지 않는다.
_QUOTE = re.compile(r"[\"“「『][^\"”」』]{2,}[\"”」』]")
# 사용자를 가리키는 호칭 가운데 방과 무관한 것 — 프로필 없는 방의 기본 호칭과 사실 추출의 사용자 표기(실행기 기본값과 같다).
_USER_ALIASES = frozenset(
    normalize_part(n) for n in excluded_user_names(PromptNames(persona_name=None, char_name=None))
)

SUMMARY_COUNTS = (
    "secretItems",
    "secretMarked",
    "secretBodyExposed",
    "relationItems",
    "relationKept",
    "relationLatestCue",
    "claimItems",
    "claimSourced",
    "claimFactualized",
)
EPISODE_COUNTS = (
    "witnessedItems",
    "witnessedFound",
    "witnessedKnownByKept",
    "confidedItems",
    "confidedFound",
    "confidedKnownByKept",
    "claimItems",
    "claimFound",
    "claimsCharacter",
    "claimNarrationMixed",
    "claimNarrationSourced",
    "detailItems",
    "detailEpisodes",
    "detailNarrationEpisodes",
)
EPISODE_RATES = {
    "witnessedKnownByRate": ("witnessedKnownByKept", "witnessedItems"),
    "confidedKnownByRate": ("confidedKnownByKept", "confidedItems"),
    "detailNarrationShare": ("detailNarrationEpisodes", "detailEpisodes"),
}
FACT_COUNTS = ("secretItems", "secretRowFound", "knownByKept", "ownerMarked", "duplicateKeyRows")
# 목적함수 파일의 기준 이름 → (분자, 분모). 분모가 없으면 개수 그대로.
SUMMARY_RATES = {
    "secretMarkedRate": ("secretMarked", "secretItems"),
    "secretBodyExposureRate": ("secretBodyExposed", "secretItems"),
    "relationKeptRate": ("relationKept", "relationItems"),
    "relationLatestCueRate": ("relationLatestCue", "relationItems"),
    "claimSourcedRate": ("claimSourced", "claimItems"),
    "claimFactualizedRate": ("claimFactualized", "claimItems"),
}
FACT_RATES = {
    "knownByKeptRate": ("knownByKept", "secretItems"),
    "secretOwnerMarkedRate": ("ownerMarked", "secretItems"),
    "secretRowFoundRate": ("secretRowFound", "secretItems"),
}
ORDERS = {
    "summary": ["secretMarkedRate", "-secretBodyExposureRate", "relationKeptRate"],
    "facts": ["knownByKeptRate", "secretOwnerMarkedRate", "-duplicateKeyCount"],
    "episodes": ["-claimNarrationMixed", "witnessedKnownByRate", "detailNarrationShare", "confidedKnownByRate"],
}


def dev_view(plants_path: Path, split_dir: Path) -> PlantSet:
    """개발 보기. 시험 절반을 고르지 않으므로 봉인 사전 등록 파일은 읽히지 않는다(자리만 채운다)."""
    return holdout.load_view(plants_path, split_dir, {"dev"}, preregistration=split_dir / "not-read", seal_sha=None)


def _dev_items(plant_set: PlantSet, item_ids: Sequence[str] | None) -> list[dict[str, Any]]:
    off = [e["id"] for e in plant_set.all_items() if e.get("split") != "dev"]
    if off:
        raise SystemExit(f"개발 보기만 센다 — 개발이 아닌 문항 {len(off)}개가 든 보기를 받았다")
    if item_ids is None:
        return plant_set.all_items()
    items = []
    for item_id in item_ids:
        if item_id in plant_set.hidden:
            raise SystemExit("시험 문항 id 는 받지 않는다 — 개발 문항으로만 센다")
        items.append(plant_set.item(item_id))
    return items


def _n(text_value: Any) -> str:
    return normalize_part(text_value) if isinstance(text_value, str) else ""


def name_forms(name: str) -> set[str]:
    full = _n(name)
    forms = {full} if len(full) >= 2 else set()
    if _HANGUL.match(full):
        forms.add(full[1:])
    return forms


def _named(text_norm: str, name: str) -> bool:
    return any(form in text_norm for form in name_forms(name))


def user_names(header: Mapping[str, Any]) -> frozenset[str]:
    """아는 사람에서 뺄 사용자 이름 — 실행기가 방 이름 목록에서 뺀 이름(머리 줄 `userNames`). 머리 줄에 없으면 실행기의 프로필
    없는 방 기본값과 같다."""
    raw = header.get("userNames")
    names = raw if raw else excluded_user_names(PromptNames(persona_name=None, char_name=None))
    return frozenset(_n(n) for n in names)


def _knowers(item: Mapping[str, Any], users: frozenset[str]) -> list[str]:
    fact = item.get("expected_fact") or {}
    return [k for k in fact.get("known_by") or [] if _n(k) not in users]


def _cues(item: Mapping[str, Any]) -> set[str]:
    words: list[str] = []
    for bundle in (item.get("answer_key") or {}).get("leak_bundles") or []:
        words += list(bundle)
    words += list(item.get("keywords") or [])
    for event in item.get("plants") or []:
        words += list(event.get("keywords") or [])
    return {_n(w) for w in words if len(_n(w)) >= 2}


def _holds_content(text_norm: str, item: Mapping[str, Any], users: frozenset[str]) -> bool:
    hits = sum(1 for cue in _cues(item) if cue in text_norm)
    people = [str(item.get("secretOwner") or ""), *_knowers(item, users)]
    return hits >= 2 or (hits >= 1 and any(_named(text_norm, p) for p in people if p))


def _segments(summary: str) -> list[str]:
    """마디 목록. 줄 머리 `-` 목록 항목은 문장이 여럿이어도 한 마디다(표기 괄호가 항목 끝 문장에만 붙는다). 그 밖의 줄은
    문장마다 나눈다. 괄호로 시작하는 마디(마침표 뒤에 띄어 붙인 표기 괄호, 다음 줄로 넘어간 표기 괄호 등)는 앞 마디에 붙인다."""
    pieces: list[str] = []
    for line in summary.splitlines():
        pieces += [line] if line.lstrip().startswith("-") else _SENTENCE.split(line)
    out: list[str] = []
    for piece in pieces:
        if not piece.strip():
            continue
        if out and piece.strip().startswith("("):
            out[-1] = f"{out[-1]} {_n(piece)}"
        else:
            out.append(_n(piece))
    return out


def _secret_marked(summary: str, item: Mapping[str, Any], users: frozenset[str]) -> bool:
    """표기가 있는 마디가 그 비밀의 단서를 하나 이상 담았다(단서와 주인·아는 인물 이름이 함께, 또는 단서 둘 이상). 주인 이름과
    표기만 있는 마디는 그 주인의 어느 비밀인지 가릴 수 없어 세지 않는다."""
    return any(_MARKER.search(s) and _holds_content(s, item, users) for s in _segments(summary))


def _body_exposed(summary: str, item: Mapping[str, Any], users: frozenset[str]) -> bool:
    return any(_holds_content(s, item, users) and not _MARKER.search(s) for s in _segments(summary))


def _relation(summary: str, item: Mapping[str, Any]) -> tuple[bool, bool]:
    fact = item.get("expected_fact") or {}
    a, b = str(fact.get("subject") or ""), str(fact.get("object") or "")
    correct = str((item.get("answer_key") or {}).get("correct") or "")
    latest = {_n(correct.split("—")[0])} if correct.strip() else set()
    events = item.get("plants") or []
    if events:
        latest |= {_n(w) for w in events[-1].get("keywords") or []}
    latest = {w for w in latest if len(w) >= 2}
    # 비밀 표기 괄호 안의 이름은 관계를 적은 것이 아니다 — 괄호를 지운 뒤 두 사람을 함께 부른 마디만 센다.
    together = [s for s in _segments(_MARKER_PAREN.sub("", summary)) if _named(s, a) and _named(s, b)]
    return bool(together), any(any(w in s for w in latest) for s in together)


def _claimed(item: Mapping[str, Any]) -> bool:
    return (item.get("expected_fact") or {}).get("truth_status") == "claimed"


def _speakers(item: Mapping[str, Any]) -> list[str]:
    said = (item.get("expected_fact") or {}).get("said_by")
    names = said if isinstance(said, list) else [said]
    return [str(n) for n in names if isinstance(n, str) and n.strip()]


def _speaker_named(text_norm: str, item: Mapping[str, Any], users: frozenset[str]) -> bool:
    """마디가 그 주장을 한 사람을 불렀다. 정답은 사용자를 고정 표기("사용자")로 적지만 요약·장면은 사용자를 방마다 다르게
    부르므로("당신"·프로필 이름), 말한 사람이 사용자 표기면 사용자 호칭 가운데 하나만 있어도 부른 것으로 본다."""
    aliases = users | _USER_ALIASES
    for speaker in _speakers(item):
        if _n(speaker) in aliases:
            if any(_named(text_norm, alias) for alias in aliases):
                return True
        elif _named(text_norm, speaker):
            return True
    return False


def _user_claim(item: Mapping[str, Any], users: frozenset[str]) -> bool:
    """말한 사람이 모두 사용자 호칭이다(말한 사람이 없으면 인물 주장으로 본다)."""
    aliases = users | _USER_ALIASES
    speakers = _speakers(item)
    return bool(speakers) and all(_n(s) in aliases for s in speakers)


def _scene_sourced(text_norm: str, item: Mapping[str, Any], users: frozenset[str]) -> bool:
    """장면 본문이 그 주장의 출처를 밝혔다 — 말한 인물 이름과 전언 표지(출처 말 또는 인용)가 함께 있다."""
    return bool(_SOURCE.search(text_norm) or _QUOTE.search(text_norm)) and _speaker_named(text_norm, item, users)


def _holds_claim(text_norm: str, item: Mapping[str, Any], users: frozenset[str]) -> bool:
    hits = sum(1 for cue in _cues(item) if cue in text_norm)
    return hits >= 2 or (hits >= 1 and _speaker_named(text_norm, item, users))


def _claim_marks(summary: str, item: Mapping[str, Any], users: frozenset[str]) -> tuple[bool, bool]:
    """(출처를 붙여 적었다, 출처 없이 적었다)."""
    sourced = factual = False
    for segment in _segments(summary):
        norm = _n(segment)
        if not _holds_claim(norm, item, users):
            continue
        if _SOURCE.search(segment):
            sourced = sourced or _speaker_named(norm, item, users)
        else:
            factual = True
    return sourced, factual


def _checkpoints(header: Mapping[str, Any]) -> dict[str, int]:
    raw = header.get("checkpointSnapshots") or {}
    if not raw:
        raise SystemExit("결과 머리 줄에 체크포인트별 스냅샷 수가 없다")
    return {str(cp): int(n) for cp, n in raw.items()}


def _asked_here(item: Mapping[str, Any], checkpoint: str) -> bool:
    offline = {str(c) for c in (item.get("probeCheckpoints") or {}).get("offline", [])}
    asked = {str(c) for c in item.get("ask_checkpoints") or []}
    return checkpoint in offline and checkpoint in asked


def summary_metrics(
    plant_set: PlantSet,
    header: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    item_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, int]]:
    items = _dev_items(plant_set, item_ids)
    users = user_names(header)
    by_index = {int(r["index"]): str(r.get("summary") or "") for r in records if r.get("kind") == "fold"}
    out: dict[str, dict[str, int]] = {}
    for cp, n in _checkpoints(header).items():
        if n not in by_index:
            raise SystemExit(f"결과에 체크포인트 {cp} 의 접기({n}번째)가 없다 — 다 돌지 않은 결과다")
        summary = by_index[n]
        row = dict.fromkeys(SUMMARY_COUNTS, 0)
        for item in items:
            if not _asked_here(item, cp):
                continue
            if item.get("category") == "secret":
                row["secretItems"] += 1
                row["secretMarked"] += _secret_marked(summary, item, users)
                row["secretBodyExposed"] += _body_exposed(summary, item, users)
            elif item.get("category") == "relation":
                kept, cue = _relation(summary, item)
                row["relationItems"] += 1
                row["relationKept"] += kept
                row["relationLatestCue"] += cue
            if _claimed(item):
                sourced, factual = _claim_marks(summary, item, users)
                row["claimItems"] += 1
                row["claimSourced"] += sourced
                row["claimFactualized"] += factual
        out[cp] = row
    return out


def episode_metrics(
    plant_set: PlantSet, meta: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    """장면 시제품 결과 전체(그 방의 모든 창)를 개발 문항으로 센다."""
    items = _dev_items(plant_set, None)
    users = user_names(meta)
    secrets = [e for e in items if e.get("category") == "secret"]
    cast = _cast(plant_set, secrets, users)
    episodes = [(_n(f"{r.get('title') or ''} {r.get('detail') or ''}"), r) for r in rows]
    out = dict.fromkeys(EPISODE_COUNTS, 0)
    for item in items:
        if item.get("category") == "secret" and item.get("subtype") in ("witnessed", "confided"):
            prefix = str(item["subtype"])
            out[f"{prefix}Items"] += 1
            matched = [r for norm, r in episodes if _holds_content(norm, item, users)]
            if not matched:
                continue
            out[f"{prefix}Found"] += 1
            latest = max(matched, key=lambda r: (int(r.get("end_turn") or 0), str(r.get("id"))))
            got = {_canonical(k, cast) for k in latest.get("known_by") or [] if _n(k) not in users}
            want = {_canonical(k, cast) for k in _knowers(item, users)}
            out[f"{prefix}KnownByKept"] += bool(got) and got == want
        if _claimed(item):
            out["claimItems"] += 1
            matched = [r for norm, r in episodes if _holds_claim(norm, item, users)]
            out["claimFound"] += bool(matched)
            if _user_claim(item, users):
                continue
            out["claimsCharacter"] += 1
            narrated = [
                norm for norm, r in episodes if r.get("asserted_by") == "narration" and _holds_claim(norm, item, users)
            ]
            if any(not _scene_sourced(norm, item, users) for norm in narrated):
                out["claimNarrationMixed"] += 1
            elif narrated:
                out["claimNarrationSourced"] += 1
        elif item.get("category") == "detail":
            out["detailItems"] += 1
            cues = _cues(item)
            matched = [r for norm, r in episodes if any(cue in norm for cue in cues)]
            out["detailEpisodes"] += len(matched)
            out["detailNarrationEpisodes"] += sum(1 for r in matched if r.get("asserted_by") == "narration")
    return out


def _cast(plant_set: PlantSet, items: Iterable[Mapping[str, Any]], users: frozenset[str]) -> list[str]:
    names = list((plant_set.raw.get("cast") or {}).get("named") or [])
    for item in items:
        names += [str(item.get("secretOwner") or ""), *_knowers(item, users), str(item.get("unawareCharacter") or "")]
    return [n for n in dict.fromkeys(names) if n]


def _canonical(name: str, cast: Sequence[str]) -> str:
    key = _n(name)
    for person in cast:
        forms = name_forms(person)
        if key in forms or any(form in key for form in forms):
            return _n(person)
    return key


def _row_text(row: Mapping[str, Any]) -> str:
    return _n(" ".join(str(row.get(k) or "") for k in ("subject", "object", "attribute", "value")))


def fact_metrics(
    plant_set: PlantSet,
    header: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    item_ids: Sequence[str] | None = None,
) -> dict[str, dict[str, int]]:
    items = _dev_items(plant_set, item_ids)
    if not any(r.get("kind") == "done" for r in rows):
        raise SystemExit("사실 결과에 완료 표지 줄이 없다 — 상한·진전 없음으로 멈춘 결과는 세지 않는다")
    users = user_names(header)
    secrets = [e for e in items if e.get("category") == "secret"]
    cast = _cast(plant_set, secrets, users)
    fact_rows = [r for r in rows if r.get("kind") == "fact"]
    out: dict[str, dict[str, int]] = {}
    for cp, n in _checkpoints(header).items():
        upto = [r for r in fact_rows if int(r["snapshotIndex"]) <= n]
        row = dict.fromkeys(FACT_COUNTS, 0)
        matched_ids: set[tuple[int, int]] = set()
        for item in secrets:
            if not _asked_here(item, cp):
                continue
            row["secretItems"] += 1
            matched = [r for r in upto if _holds_content(_row_text(r), item, users)]
            matched_ids |= {(int(r["snapshotIndex"]), int(r["ordinal"])) for r in matched}
            if not matched:
                continue
            latest = max(matched, key=lambda r: (int(r["snapshotIndex"]), int(r["ordinal"])))
            row["secretRowFound"] += 1
            got = {_canonical(k, cast) for k in latest.get("knownBy") or [] if _n(k) not in users}
            want = {_canonical(k, cast) for k in _knowers(item, users)}
            row["knownByKept"] += bool(latest.get("knownBy")) and got == want
            row["ownerMarked"] += _named(_n(latest.get("value")), str(item.get("secretOwner") or ""))
        seen: dict[tuple[int, str], int] = {}
        for r in upto:
            if (int(r["snapshotIndex"]), int(r["ordinal"])) in matched_ids:
                key = (int(r["snapshotIndex"]), str(r.get("factKey")))
                seen[key] = seen.get(key, 0) + 1
        row["duplicateKeyRows"] = sum(c - 1 for c in seen.values())
        out[cp] = row
    return out


def _with_rates(counts: Mapping[str, int], rates: Mapping[str, tuple[str, str]]) -> dict[str, Any]:
    """비율의 분자·분모 칸이 없으면(그 칸이 생기기 전에 만든 결과) 그 비율은 모름(None)이다 — 0 으로 채우면 "그런 문항이
    0개"와 "옛 결과라 모름"이 구별되지 않는다."""
    out: dict[str, Any] = dict(counts)
    for name, (num, den) in rates.items():
        out[name] = counts[num] / counts[den] if num in counts and counts.get(den) else None
    if "duplicateKeyRows" in counts:
        out["duplicateKeyCount"] = counts["duplicateKeyRows"]
    return out


def report(kind: str, version: str, per_work: Mapping[str, Mapping[str, Mapping[str, int]]]) -> dict[str, Any]:
    """작품마다와 합친 개수·비율. 합친 비율은 작품 개수를 더한 뒤 나눈다(작품마다 비율의 평균이 아니다).

    합칠 때는 그 체크포인트를 가진 모든 작품에 있는 칸만 더한다. 작품 일부에만 있는 칸(그 칸이 생기기 전 결과와 섞였을 때)은
    합친 결과에서 빠지고 그 칸을 쓰는 비율은 모름이 된다 — 칸이 있는 작품만 더하면 합친 숫자가 전체 작품의 숫자처럼 읽힌다."""
    if kind not in ORDERS:
        raise SystemExit(f"지표 종류는 {sorted(ORDERS)} 중 하나다: {kind}")
    rates = {"summary": SUMMARY_RATES, "facts": FACT_RATES, "episodes": EPISODE_RATES}[kind]
    rows_by_cp: dict[str, list[Mapping[str, int]]] = {}
    for counts_by_cp in per_work.values():
        for cp, counts in counts_by_cp.items():
            rows_by_cp.setdefault(cp, []).append(counts)
    pooled: dict[str, dict[str, int]] = {}
    for cp, rows in rows_by_cp.items():
        shared = [key for key in rows[0] if all(key in row for row in rows)]
        pooled[cp] = {key: sum(row[key] for row in rows) for key in shared}
    return {
        "kind": kind,
        "version": version,
        "order": ORDERS[kind],
        "works": {
            work: {cp: _with_rates(c, rates) for cp, c in sorted(by_cp.items())} for work, by_cp in per_work.items()
        },
        "pooled": {cp: _with_rates(c, rates) for cp, c in sorted(pooled.items())},
    }
