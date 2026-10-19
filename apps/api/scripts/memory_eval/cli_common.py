"""측정 하네스 CLI 의 공용 부분 — 전역 인자, 하위 명령 묶음들이 함께 쓰는 인자 묶음·출력·원장·심기 표 입구.

하위 명령은 묶음 모듈마다 `register(sub)` 로 등록한다(`memory_eval_cli.py` 가 묶음 목록을 차례로 부른다). 묶음 모듈은 이 모듈만
공유하고 서로 import 하지 않는다 — 그래야 판정 모듈이 없는 묶음(인프라)이 판정 모듈을 끌고 오지 않는다."""

import argparse
import json
import math
from pathlib import Path
from typing import Any

from memory_eval import holdout, plants as plants_mod
from memory_eval.ledger import Ledger
from memory_eval.seal import PREREGISTRATION_FILE, require_seal

# 카운트다운·대본 검사가 읽는 튜토리얼 작품 글 — 저장소의 시드라 측정 데이터가 아니다.
DEFAULT_SEED_JSON = Path(__file__).resolve().parents[1] / "seed_content/data/tutorial/stories/tutorial-filmclub.json"


def add_global_args(ap: argparse.ArgumentParser) -> None:
    """하위 명령 앞에 주는 전역 인자."""
    ap.add_argument("--run", type=Path, required=True, help="원자료 폴더(대본·덤프·원장·결과)")
    ap.add_argument(
        "--data-dir",
        type=Path,
        help="측정 데이터 폴더(대본·심기 표·명세 — 공개 저장소 밖). 기본 경로가 없다: 데이터를 읽는 명령은 이 인자를 요구한다",
    )
    ap.add_argument(
        "--status-dir",
        type=Path,
        help="상태 파일(status.json)과 끝난 뒤 완료 표지(done.<종료 코드>)를 쓸 폴더 — 오래 도는 명령을 밖에서 지켜볼 때",
    )
    ap.add_argument("--cap-usd", type=float, help="승인 묶음 상한(넘지 않는다) — 유료 실행은 명시해야 한다")
    ap.add_argument(
        "--halt-usd", type=float, help="묶음 누적 멈춤 선(닿으면 멈추고 묻는다) — 유료 실행은 명시해야 한다"
    )
    ap.add_argument(
        "--bundle", help="승인 묶음 이름(원장 행에 적히고 멈춤은 이 묶음 누적으로 본다) — 유료 실행은 명시해야 한다"
    )


def data_file(args: argparse.Namespace, name: str) -> Path:
    """측정 데이터 폴더 안의 파일. 데이터는 공개 저장소에 두지 않으므로 기본 폴더가 없다 — 전역 인자를 빠뜨리면 저장소 안의
    엉뚱한 파일을 조용히 읽지 않고 멈춘다."""
    data_dir: Path | None = args.data_dir
    if data_dir is None:
        raise SystemExit(f"측정 데이터 폴더(--data-dir, 하위 명령 앞)를 줘야 {name} 를 읽는다")
    path = data_dir / name
    if not path.is_file():
        raise SystemExit(f"측정 데이터 폴더에 {name} 가 없다: {path}")
    return path


def with_plants(p: argparse.ArgumentParser) -> None:
    p.add_argument("--plants", type=Path, required=True)
    p.add_argument("--split-dir", type=Path, help="2차 형식 분할 폴더(기본 <원자료>/split)")


def with_splits(p: argparse.ArgumentParser) -> None:
    p.add_argument("--splits", default="dev", help="dev · test · dev,test (시험 절반은 봉인 해시가 있어야 한다)")
    p.add_argument("--seal-sha", help="이번 런 봉인 사전 등록의 sha256")


def paid(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-paid", action="store_true", help="유료 호출을 실제로 한다(사용자 승인 뒤에만)")


def write_status(status_dir: Path, status: dict[str, Any]) -> None:
    """상태 파일을 통째로 바꿔 쓴다(임시 파일 뒤 이름 바꾸기) — 지켜보는 쪽이 반쯤 쓴 JSON 을 읽지 않게."""
    status_dir.mkdir(parents=True, exist_ok=True)
    tmp = status_dir / "status.json.tmp"
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(status_dir / "status.json")


def read_status(status_dir: Path) -> dict[str, Any]:
    path = status_dir / "status.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def update_status(status_dir: Path, fields: dict[str, Any]) -> None:
    """상태 파일에 칸을 더하거나 바꾼다(명령이 진행 중에 남기는 작업자별 진행 등). 진입점이 쓴 칸은 그대로 둔다."""
    write_status(status_dir, {**read_status(status_dir), **fields})


def _range(raw: str) -> tuple[int, int]:
    low, high = raw.split(",")
    return int(low), int(high)


def _ints(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


def _splits(args: argparse.Namespace) -> set[str]:
    splits = set(args.splits.split(","))
    require_seal(splits, args.run / PREREGISTRATION_FILE, seal_sha=args.seal_sha)
    return splits


def _ledger(args: argparse.Namespace) -> Ledger:
    """원장 — 묶음 상한·멈춤 선·승인 묶음은 실행 인자. 유료 호출을 하는 실행은 셋을 모두 명시해야 돈다(기본값이 있으면 상한만
    올린 실행이 옛 멈춤 선에서 조용히 먼저 멈춘다). 돈을 쓰지 않는 실행(드라이런·견적·원장 요약)은 읽기만 하므로 없어도 된다."""
    paid = bool(getattr(args, "allow_paid", False)) and not getattr(args, "dry_run", False)
    missing = [
        flag
        for flag, value in (("--cap-usd", args.cap_usd), ("--halt-usd", args.halt_usd), ("--bundle", args.bundle))
        if value is None
    ]
    if paid and missing:
        raise SystemExit(f"유료 실행은 {', '.join(missing)} 를 명시해야 한다(묶음 상한·멈춤 선·승인 묶음)")
    return Ledger(
        args.run / "ledger.jsonl",
        cap_usd=math.inf if args.cap_usd is None else args.cap_usd,
        halt_usd=args.halt_usd,
        bundle=args.bundle,
    )


def _plant_view(args: argparse.Namespace, splits: set[str] | None = None) -> plants_mod.PlantSet:
    """심기 표를 읽는 모든 명령의 입구. 1차 형식은 항목의 분할 칸을 그대로 쓰고, 2차 형식은 분할 파일로 보기를 만든다 — 절반을
    주지 않으면 개발 보기이고, 시험 절반은 봉인 확인을 지나야 시험 정답 파일을 연다."""
    raw = json.loads(args.plants.read_text(encoding="utf-8"))
    if not holdout.is_v2(raw):
        return plants_mod.load_plants(args.plants)
    return holdout.load_view(
        args.plants,
        args.split_dir or args.run / holdout.SPLIT_DIR,
        splits or {"dev"},
        preregistration=args.run / PREREGISTRATION_FILE,
        seal_sha=getattr(args, "seal_sha", None),
    )


def _refuse_v2(args: argparse.Namespace, command: str) -> None:
    if holdout.is_v2(json.loads(args.plants.read_text(encoding="utf-8"))):
        raise SystemExit(
            f"{command} 는 1차 형식 심기 표 전용이다(2차 형식은 항목에 분할 칸이 없고 시험 문항을 함께 읽게 된다)"
        )


def _db_url(*, writes: bool) -> str:
    from memory_eval.runtime import work_database_url

    return work_database_url(writes=writes)


def _embedding_table(args: argparse.Namespace) -> Any:
    from memory_eval.embed_offline import EmbeddingTable

    if not args.embed_model or not args.embed_dims:
        raise SystemExit("임베딩 회상은 --embed-model 과 --embed-dims 를 함께 준다")
    if args.embeddings is None or not args.embeddings.exists():
        return EmbeddingTable(model=args.embed_model, dims=args.embed_dims, vectors={})
    return EmbeddingTable.load(args.embeddings, model=args.embed_model, dims=args.embed_dims)


def _replay_embeddings(args: argparse.Namespace, arms: list[str]) -> Any:
    """임베딩 회상을 켠 갈래가 있으면 질의 벡터 파일, 없으면 None. 그 갈래가 있는데 벡터 파일을 주지 않았으면 무엇을 읽기 전에
    거부한다 — 클라이언트 없이 조립하면 앱이 조용히 명사 단독으로 조립한다."""
    from memory_eval.offline_embedding import embedding_arms

    needs = embedding_arms(arms)
    if not needs:
        return None
    if args.embeddings is None:
        raise SystemExit(
            f"임베딩 회상 갈래 {needs} 는 --embeddings 질의 벡터 파일(과 --embed-model·--embed-dims)을 줘야 한다"
        )
    return _embedding_table(args)


def _hybrid_params(args: argparse.Namespace) -> Any:
    from memory_eval import embed_offline as eo

    return eo.HybridParams(
        **{name: getattr(args, f"{eo.CONFIG_PREFIX}{name}") for name in eo.HybridParams.__dataclass_fields__}
    )


def _optional_int(raw: str) -> int | None:
    return None if raw.strip().lower() == "none" else int(raw)


def _axis(cast: Any) -> Any:
    def parse(raw: str) -> list[Any]:
        return [cast(part) for part in raw.split(",") if part.strip()]

    return parse


def _hybrid_args(p: argparse.ArgumentParser, *, grid: bool) -> None:
    """하이브리드 회상 설정 — 운영 설정 이름 그대로(기본값도 운영 기본값). `grid` 면 축마다 쉼표 목록을 받는다."""
    from memory_eval import embed_offline as eo

    casts: dict[str, Any] = {"rrf_k": int, "max_plain": int, "max_cue": int, "max_distance": float,
                             "vector_limit": int, "df_max": _optional_int}  # fmt: skip
    for name, spec in eo.HybridParams.__dataclass_fields__.items():
        flag = f"--{eo.CONFIG_PREFIX}{name}".replace("_", "-")
        flags = [flag, "--rrf-k"] if name == "rrf_k" else [flag]
        cast = casts[name]
        if grid:
            p.add_argument(
                *flags,
                dest=f"{eo.CONFIG_PREFIX}{name}",
                type=_axis(cast),
                default=[spec.default],
                help=f"격자 축(쉼표 목록, 없음은 none). 기본 {spec.default}",
            )
        else:
            p.add_argument(*flags, dest=f"{eo.CONFIG_PREFIX}{name}", type=cast, default=spec.default,
                           help=f"기본 {spec.default}(운영 기본값)")  # fmt: skip


def _replay_embedding_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--embeddings", type=Path, help="임베딩 회상 갈래의 질의 벡터 파일(JSONL, embed-run 출력 꼴)")
    p.add_argument("--embed-model", help="측정 서버 env 의 MEMORY_EMBED_MODEL 과 같게")
    p.add_argument("--embed-dims", type=int, help="측정 서버 env 의 MEMORY_EMBED_DIMS 와 같게")
    _hybrid_args(p, grid=False)


def _paid(args: argparse.Namespace) -> bool:
    return bool(args.allow_paid) and not args.dry_run


def _probe_rows(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
