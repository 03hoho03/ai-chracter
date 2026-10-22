"""판정 일치율을 잴 생성 응답을 만드는 준비 — 대본 읽기, 엔딩 갈래 한 턴 치기, 드라이버 로그로 카운트다운 층 표 만들기, 생성
원가 견적.

대본은 스토리·캐릭터 두 파일이고(측정 데이터 폴더에 둔다, 이름은 `STORY_SCRIPT_FILE`·`CHARACTER_SCRIPT_FILE`) 턴마다 층 태그를
단다. 층 표는 대본 순서가 아니라 드라이버 로그의 끝난 턴 줄(`clientTurn`, 덤프의 턴 번호)과 `--tag` 로 준 태그로 만든다 — 대본
순서로 세면 잃은 턴을 다시 칠 때 층이 한 칸씩 어긋난다.

엔딩은 한 방에서 한 번 발동하면 그 방의 스탯·엔딩 판정이 멈춰, 이어 치면 발동한 엔딩 판정 줄이 하나밖에 남지 않는다. 그래서
스토리 대본은 엔딩 층을 갈래(`branches`)로 둔다: 대본을 끝낸 뒤 `ending-stats` 로 스탯을 문턱 위에 올린 상태를 얼리고, 갈래마다
그 템플릿에서 작업 DB 를 새로 만든 다음 엔딩 판정 차례인 턴 하나만 보낸다. 갈래들은 방도 턴 번호도 같으므로 덤프 파일 이름으로
판정 줄을 구분한다.

생성 모델은 운영 메인과 같은 Opus 직결이다. 견적은 프롬프트 캐시를 가정한다 — 첫 턴에 프롬프트 전체를 캐시에 쓰고, 이후 턴은
앞까지를 캐시에서 읽으며 새로 붙은 부분(직전 사용자 말과 응답)만 쓴다. 5분 넘게 쉬어 캐시가 끊긴 턴은 전체를 다시 쓰므로 이
견적은 아래쪽 값에 가깝다."""

import asyncio
import json
import os
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memory_eval.ledger import cost_usd
from memory_eval.server import API_DIR

if TYPE_CHECKING:
    from memory_eval.judge_agreement import JudgmentLine

# 아래 셋은 측정 데이터 폴더 안의 파일 이름이다(공개 저장소에 두지 않는다) — 부르는 쪽이 데이터 폴더 경로와 합쳐 준다.
STORY_SCRIPT_FILE = "judge_script_story.json"
CHARACTER_SCRIPT_FILE = "judge_script_character.json"
CONTROLS_CONFIG_FILE = "judge_controls.json"
GENERATION_MODEL = "claude-opus-5-5"
STORY_DUMP = "dump-story.jsonl"
CHARACTER_DUMP = "dump-character.jsonl"


def load_script(path: Path) -> dict[str, Any]:
    script: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    tagged = script["turns"] + script.get("branches", [])
    unknown = sorted({turn["stratum"] for turn in tagged} - set(script["strata"]))
    if unknown:
        raise SystemExit(f"{path.name}: 층 정의에 없는 층 태그 {unknown}")
    return script


def branch_turn(script: Mapping[str, Any]) -> int:
    """갈래 턴의 번호 — 대본의 마지막 턴 바로 뒤 번호다(사용자 첫 턴이 1)."""
    return len(script["turns"]) + 1


def branch_dir(run_dir: Path, branch_id: str) -> Path:
    return run_dir / "branches" / branch_id


def branch_dump_name(branch_id: str) -> str:
    """갈래마다 다른 파일 이름 — 판정 줄 id 가 `<파일 이름>:<줄 번호>` 라 이름이 같으면 갈래가 섞인다."""
    return f"dump-story-{branch_id}.jsonl"


def branch_dump(run_dir: Path, branch_id: str) -> Path:
    return branch_dir(run_dir, branch_id) / branch_dump_name(branch_id)


def run_branch(
    branch: Mapping[str, Any],
    *,
    database_url: str,
    run_dir: Path,
    room_id: uuid.UUID,
    checkpoint_no: int,
    label: str,
    port: int,
    cred_file: Path,
    cookie_file: Path,
    server_overrides: Mapping[str, str],
    allow_paid: bool,
) -> dict[str, Any]:
    """갈래 한 번 실행: 템플릿에서 작업 DB 를 새로 복제(지문 확인) → 그 갈래 덤프 경로로 서버를 띄움 → 드라이버가 누적 기준을
    다시 맞춘 뒤 갈래의 사용자 말 한 턴을 보냄 → 서버를 내림. 작업 DB 이름이 `lm_eval_` 접두가 아니면 무엇도 하기 전에 멈춘다."""
    from memory_eval import checkpoint, server
    from memory_eval.probe import _last_turn

    checkpoint.ensure_eval_db_name(checkpoint.database_name(database_url))
    folder = branch_dir(run_dir, str(branch["id"]))
    folder.mkdir(parents=True, exist_ok=True)
    restored = asyncio.run(
        checkpoint.restore(
            database_url,
            work_db=checkpoint.database_name(database_url),
            checkpoint=checkpoint_no,
            room_id=room_id,
            dumps_dir=run_dir / "dumps",
            label=label,
            # 엔딩 갈래 템플릿은 `freeze` 가 투입을 그대로 얼린 A 계열이다. B 지문을 잘못 주면 요약 해시 칸이 남아 거부된다.
            b_series=False,
        )
    )
    overrides = {
        **server_overrides,
        "DATABASE_URL": database_url,
        "PROMPT_DUMP_PATH": str(branch_dump(run_dir, str(branch["id"]))),
    }
    handle = server.start(overrides, port=port, log=folder / "server.log", allow_paid=allow_paid)
    try:
        code = _drive(handle.base, folder, room_id, cred_file, cookie_file, database_url, "--rebase", "엔딩 갈래 복원")
        if code == 0:
            say = ("--say", str(branch["say"]), "--tag", str(branch["stratum"]))
            code = _drive(handle.base, folder, room_id, cred_file, cookie_file, database_url, *say)
    finally:
        server.stop(handle)
    last = _last_turn(folder) or {}
    return {
        "branch": branch["id"],
        "stratum": branch["stratum"],
        "exit": code,
        "clientTurn": last.get("clientTurn"),
        "saved": bool(last.get("reply")),
        "fingerprint": restored["fingerprint"],
        "dump": str(branch_dump(run_dir, str(branch["id"]))),
    }


def _drive(
    base: str, folder: Path, room_id: uuid.UUID, cred_file: Path, cookie_file: Path, database_url: str, *extra: str
) -> int:
    """측정 드라이버 한 번(프로브와 같은 모양). 드라이버 명령에도 같은 작업 DB 를 준다."""
    command = [
        "uv", "run", "--env-file", ".env", "python", "scripts/chat_play.py",
        "--base", base, "--cred-file", str(cred_file), "--cookie-file", str(cookie_file),
        "--log", str(folder / "chat.jsonl"), "--snapshot-log", str(folder / "memory-snapshots.jsonl"),
        "--room", str(room_id), *extra,
    ]  # fmt: skip
    env = {**os.environ, "DATABASE_URL": database_url}
    with (folder / "driver.out").open("ab") as out:
        return subprocess.run(
            command, cwd=API_DIR, env=env, stdout=out, stderr=subprocess.STDOUT, check=False
        ).returncode


def load_controls_config(path: Path) -> dict[str, Any]:
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return config


def cell_control_turns(story: Mapping[str, Any]) -> list[int]:
    """칸 대조군 후보 — 칸 해당 아님(`cellMatch` 거짓)이고 대조군에서 빼라는 표시(`controlEligible` 거짓)가 없는 턴. 칸 해당 여부는
    사용자 말만으로 사람마다 갈려, 해당 아님이어도 한 표시자가 애매로 본 턴은 노린 칸을 이미 고른 줄일 수 있어 뺀다."""
    return [
        n
        for n, turn in enumerate(story["turns"], start=1)
        if not turn["cellMatch"] and turn.get("controlEligible", True)
    ]


def build_controls(
    lines: "Sequence[JudgmentLine]",
    *,
    story: Mapping[str, Any],
    character: Mapping[str, Any],
    strata: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """망친 입력 대조군 명세를 정한 규칙으로 만든다 — 판정 결과·덤프의 다음 턴 스탯 값을 보지 않고, 대본·확정 층 표·덤프 프롬프트만
    읽는다. 호출 위치마다 후보 턴을 정한 순서로 훑어 그 턴의 판정 줄 중 첫 줄(줄 번호가 가장 작은 것)을 원래 줄로 삼고, 그 턴의
    사용자 말 뒤에 정한 문장을 붙인다. 사용자 말이 프롬프트에 정확히 한 번 있지 않으면 그 턴은 건너뛴다.

    - 스탯: 확정 층 표에 남은 S-a 턴(한 방 덤프), 앞에서부터.
    - 엔딩: E-miss 갈래 전부(갈래 덤프).
    - 미디어 북 칸: `cell_control_turns` 의 한 방 턴, 앞에서부터.
    - 상황 이미지: 캐릭터 대본에 노출 조건 해당 아님(`imageCondition` 거짓)으로 적은 턴, 앞에서부터.

    모자란 호출 위치는 `shortfall` 에 모자란 수를 남긴다."""
    per_site = int(config["perCallSite"])
    sentences: Mapping[str, str] = config["sentences"]
    kept_sa = sorted(int(e["turn"]) for e in strata if e["stratum"] == "S-a")
    story_says = {n: str(t["say"]) for n, t in enumerate(story["turns"], start=1)}
    candidates: dict[str, list[tuple[str, int, str]]] = {
        "chat_stat_judgment": [(STORY_DUMP, n, story_says[n]) for n in kept_sa],
        "chat_ending_judgment": [
            (branch_dump_name(str(b["id"])), branch_turn(story), str(b["say"]))
            for b in story["branches"]
            if b["stratum"] == "E-miss"
        ],
        "chat_media_book_image": [(STORY_DUMP, n, story_says[n]) for n in cell_control_turns(story)],
        "chat_situational_image": [
            (CHARACTER_DUMP, n, str(t["say"]))
            for n, t in enumerate(character["turns"], start=1)
            if not t["imageCondition"]
        ],
    }
    controls: list[dict[str, Any]] = []
    shortfall: dict[str, int] = {}
    for site, turns in candidates.items():
        picked = 0
        for file, turn, say in turns:
            if picked == per_site:
                break
            matching = sorted(
                (
                    line
                    for line in lines
                    if line.line_id.rsplit(":", 1)[0] == file and line.turn == turn and line.call_site == site
                ),
                key=lambda line: int(line.line_id.rsplit(":", 1)[1]),
            )
            if not matching or matching[0].prompt.count(say) != 1:
                continue
            controls.append(
                {
                    "id": f"{site}:{file}:{turn}",
                    "base": {"lineId": matching[0].line_id},
                    "replace": [[say, f"{say} {sentences[site]}"]],
                }
            )
            picked += 1
        if picked < per_site:
            shortfall[site] = per_site - picked
    return {"controls": controls, "shortfall": shortfall}


def strata_from_log(log: Path, script: Mapping[str, Any]) -> list[dict[str, Any]]:
    """끝난 턴 줄 중 대본의 층 태그가 붙은 것만 [{roomId, turn, stratum, expectDecrement}]. 같은 턴 번호가 둘이면 끝난 줄이 하나뿐이다
    (유실 턴은 끝나지 않았다)."""
    strata = script["strata"]
    out: list[dict[str, Any]] = []
    for raw in log.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if row.get("kind") != "turn" or not row.get("done") or row.get("tag") not in strata:
            continue
        tag = row["tag"]
        out.append(
            {
                "roomId": row["roomId"],
                "turn": int(row["clientTurn"]),
                "stratum": tag,
                "expectDecrement": strata[tag]["expectDecrement"],
            }
        )
    return out


def generation_estimate(
    *,
    turns: int,
    prompt_tokens: int,
    new_tokens_per_turn: int,
    output_tokens: int,
    cold_turns: int = 0,
    model: str = GENERATION_MODEL,
) -> dict[str, Any]:
    """턴당 프롬프트 `prompt_tokens`(평균), 그중 앞 턴 뒤로 새로 붙는 토큰 `new_tokens_per_turn`, 출력 `output_tokens`.
    `cold_turns` 는 템플릿에서 복원해 서버를 새로 띄우고 치는 갈래 턴 수 — 앞 턴 캐시가 없어 첫 턴처럼 전체를 쓴다."""
    first = cost_usd(
        model,
        input_tokens=prompt_tokens,
        cached_tokens=0,
        cache_write_tokens=prompt_tokens,
        output_tokens=output_tokens,
        thoughts_tokens=0,
    )
    later = cost_usd(
        model,
        input_tokens=prompt_tokens,
        cached_tokens=prompt_tokens - new_tokens_per_turn,
        cache_write_tokens=new_tokens_per_turn,
        output_tokens=output_tokens,
        thoughts_tokens=0,
    )
    usd = (first + later * max(turns - 1, 0) if turns else 0.0) + first * cold_turns
    return {
        "model": model,
        "turns": turns,
        "coldTurns": cold_turns,
        "promptTokens": prompt_tokens,
        "newTokensPerTurn": new_tokens_per_turn,
        "outputTokens": output_tokens,
        "firstTurnUsd": first,
        "laterTurnUsd": later,
        "usd": usd,
    }
