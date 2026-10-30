"""측정 런 묶음의 턴 기록(`chat_turns`)을 로컬 DB 에서 읽어 그 묶음 폴더의 `chat-turns.jsonl` 로 쓴다.

    uv run python scripts/chat_lab_export_turns.py --run-dir <묶음 폴더> [--database-url <로컬 DB>] [--force] [--root <런 루트>]

묶음은 그 폴더 바로 아래의 드라이버 로그다(측정 서버가 묶음을 찾는 규칙과 같다). 폴더에 서로 다른 방의 드라이버 로그가 여럿이면
내보내기 함수가 거부한다(측정 서버의 내보내기 요청과 같은 규칙).
`--database-url` 이 없으면 설정의 DB 주소를 쓴다. 어느 쪽이든 로컬 DB 가 아니면 아무것도 읽지 않고 끝난다. 측정 컨테이너 DB 처럼
런을 돈 DB 가 따로 있으면 그 주소를 준다 — DB 에는 그 방의 마지막 상태만 있다(파일 머리 줄에 그렇게 적힌다).

종료 코드: 0 썼다, 1 입력이 없거나 거부했다(이미 있음·보관 폴더·방 없음·행 0 등), 3 로컬 DB 가 아니다. 2 는 argparse 가 인자
오류에 쓰는 코드라 겹치지 않게 비워 둔다."""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from chat_lab.bundles import discover_bundles
from chat_lab.export_turns import ExportRefusedError, export_chat_turns, read_only_engine
from replay.local_db import ensure_local_database

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "probe-runs"
# 로컬 DB 가 아닐 때의 종료 코드(argparse 의 인자 오류 2 와 갈리게).
EXIT_NOT_LOCAL_DB = 3


@asynccontextmanager
async def open_session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = read_only_engine(database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


def _settings_database_url() -> str:
    # 설정은 이 명령에서만 읽는다(라이브러리 층과 측정 서버 앱은 받은 주소만 쓴다).
    from api.core.config import settings

    return settings.database_url


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True, help="드라이버 로그가 있는 묶음 폴더")
    parser.add_argument("--database-url", help="턴 기록을 읽을 로컬 DB(기본: 설정의 DB 주소)")
    parser.add_argument("--force", action="store_true", help="이미 있는 chat-turns.jsonl 을 바꾼다")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="측정 런 루트(기본 apps/api/probe-runs)")
    args = parser.parse_args(argv)

    database_url = args.database_url if args.database_url is not None else _settings_database_url()
    try:
        ensure_local_database(database_url, tool="chat-lab")
    except SystemExit as refusal:
        print(refusal, file=sys.stderr)
        return EXIT_NOT_LOCAL_DB

    root = args.root.resolve()
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir() or not run_dir.is_relative_to(root):
        print(f"묶음 폴더가 없거나 런 루트({root}) 밖이다: {run_dir}", file=sys.stderr)
        return 1
    bundles = discover_bundles(root, folder=run_dir)
    if not bundles:
        print(f"이 폴더 바로 아래에 드라이버 로그가 없다: {run_dir}", file=sys.stderr)
        return 1

    try:
        async with open_session(database_url) as session:
            written = await export_chat_turns(session, bundles[0], force=args.force)
    except ExportRefusedError as refused:
        print(refused, file=sys.stderr)
        return 1
    print(f"턴 기록을 썼다: {written}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
