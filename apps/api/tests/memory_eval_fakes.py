"""측정 하네스 테스트가 함께 쓰는 지어낸 측정 데이터.

판정 문구·거짓 전제 판정 정의는 실제 측정 데이터라 저장소에 두지 않는다. 테스트는 같은 꼴의 지어낸 값으로 파일을 만들어
`--data-dir` 로 주거나 함수에 바로 넘긴다. 문장은 판정 입력의 꼴(자리표시·칸 이름)만 맞춘 것이고 실제 문안과 무관하다."""

import json
from pathlib import Path
from typing import Any

from memory_eval.judge import JUDGE_WORDING_FILE, VERDICTS, JudgeWording, load_wording


def fake_wording_raw() -> dict[str, Any]:
    return {
        "instructions": {
            kind: f"지어낸 {kind} 지시문. 라벨은 {' · '.join(labels)}." for kind, labels in VERDICTS.items()
        },
        "claimUser": "{claim} — 지어낸 사용자 발화 표시.",
        "claimCharacter": "{claim} — {who} 의 지어낸 발화 표시.",
        "namelessRole": "{role} — 지어낸 이름 없는 역할 표시",
        "abstainNoFact": "지어낸 빈 사실 칸.",
        "falsePremiseReplies": {
            "rejected": "지어낸 부정 응답.",
            "unaddressed": "지어낸 화제 돌리기 응답.",
            "userLieUnaddressed": "지어낸 속아 주는 대사.",
            "userLieAccepted": "*지어낸 서술이 거짓을 사실로 적는다.*",
        },
    }


def write_fake_wording(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / JUDGE_WORDING_FILE
    path.write_text(json.dumps(fake_wording_raw(), ensure_ascii=False), encoding="utf-8")
    return path


def fake_wording(tmp_path: Path) -> JudgeWording:
    return load_wording(write_fake_wording(tmp_path / "wording-data"))


def fake_false_premise_definitions() -> dict[str, Any]:
    labels = {"rejected": "지어낸 부정 정의.", "accepted": "지어낸 받아들임 정의.", "unaddressed": "지어낸 미결 정의."}
    return {
        "claimVerdicts": dict(labels),
        "claimNote": "지어낸 판정 주의.",
        "lieVerdicts": {**labels, "rejected": "지어낸 부정 정의, 진실은 {truth}."},
        "lieNote": "지어낸 거짓말 판정 주의.",
    }


def fake_wording_now() -> JudgeWording:
    """파일 없이 바로 쓰는 지어낸 판정 문구(파일 읽기와 같은 값)."""
    raw = fake_wording_raw()
    return JudgeWording(
        instructions=raw["instructions"],
        claim_user=raw["claimUser"],
        claim_character=raw["claimCharacter"],
        nameless_role=raw["namelessRole"],
        abstain_no_fact=raw["abstainNoFact"],
        false_premise_replies=raw["falsePremiseReplies"],
    )


def fake_boundary_rows() -> list[dict[str, Any]]:
    """지어낸 경계 견본 — 비밀·화자·거짓 전제의 라벨마다 한 줄(비밀 2, 화자 4, 거짓 전제 3)."""
    entries: dict[str, dict[str, Any]] = {
        "secret": {
            "category": "secret",
            "question": "지어낸 질문?",
            "secretOwner": "가상인물갑",
            "unawareCharacter": "가상인물을",
            "expected_fact": {"attribute": "지어낸 비밀", "value": "가상값"},
        },
        "speaker": {
            "category": "speaker",
            "question": "지어낸 질문?",
            "answer_key": {"who": "가상인물갑", "claim": "지어낸 주장"},
        },
        "false_premise": {
            "category": "false_premise",
            "subtype": "character_claim",
            "question": "지어낸 질문?",
            "answer_key": {"premise": "지어낸 거짓 전제", "truth": "지어낸 진실"},
        },
    }
    return [
        {
            "id": f"boundary-{kind}-{label}",
            "kind": kind,
            "entry": dict(entry),
            "expected": label,
            "replies": [f"지어낸 응답 {kind} {label}"],
            "definition": f"지어낸 라벨 정의 {kind} {label}",
        }
        for kind, entry in entries.items()
        for label in VERDICTS[kind]
    ]


def write_fake_data_dir(data_dir: Path, boundary_rows: list[dict[str, Any]] | None = None) -> Path:
    """판정 명령이 읽는 지어낸 데이터 폴더 — 판정 문구와 경계 견본."""
    from memory_eval.judge import BOUNDARY_CONTROLS_FILE

    write_fake_wording(data_dir)
    rows = fake_boundary_rows() if boundary_rows is None else boundary_rows
    (data_dir / BOUNDARY_CONTROLS_FILE).write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    return data_dir
