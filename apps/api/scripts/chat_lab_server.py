"""로컬 측정 서버(chat-lab)를 띄운다 — 측정 런 폴더를 읽어 측정 웹 화면에 HTTP 로 낸다.

    uv run python scripts/chat_lab_server.py [--port 8791] [--root probe-runs] [--database-url <로컬 DB>]
    uv run python scripts/chat_lab_server.py --dump-openapi

바인드는 127.0.0.1 고정이다(호스트를 바꾸는 인자는 없다) — 덤프에 시험 대화 원문이 있어 같은 망의 다른 기기가 읽지 못하게 한다.
DB 는 턴 기록 내보내기 요청 때만 읽고, `--database-url` 이 없으면 설정의 DB 주소를 쓴다. 어느 쪽이든 로컬 DB 가 아니면 띄우지
않는다.

`--dump-openapi` 는 앱 스키마만 `apps/chat-lab/openapi.json` 에 쓰고 끝난다. 가드·DB·설정의 DB 주소·런 루트 어느 것도 보지 않는다
— CI 러너에는 `.env` 도 기본 DB 도 없는데, 같은 커밋에서 떨군 바이트가 커밋된 파일과 같아야 하기 때문이다. 직렬화는 운영 API 의
스키마 내보내기(`scripts/export_openapi.py`)와 같다."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from chat_lab.app import create_app

API_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = API_DIR / "probe-runs"
OPENAPI_PATH = API_DIR.parent / "chat-lab" / "openapi.json"
HOST = "127.0.0.1"
DEFAULT_PORT = 8791


def openapi_text() -> str:
    """앱을 만들기만 하고(DB 주소 없음, 런 루트는 보지 않는다) 스키마를 직렬화한 글."""
    spec = create_app(root=DEFAULT_ROOT, database_url=None).openapi()
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def _settings_database_url() -> str:
    # 설정은 서버를 띄울 때만 읽는다 — 스키마 떨구기는 여기까지 오지 않는다.
    from api.core.config import settings

    return settings.database_url


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="측정 런 루트(기본 apps/api/probe-runs)")
    parser.add_argument("--database-url", help="턴 기록을 내보낼 로컬 DB(기본: 설정의 DB 주소)")
    parser.add_argument(
        "--dump-openapi", action="store_true", help="스키마만 apps/chat-lab/openapi.json 에 쓰고 끝낸다"
    )
    args = parser.parse_args(argv)

    if args.dump_openapi:
        OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENAPI_PATH.write_text(openapi_text(), encoding="utf-8")
        print(f"스키마를 썼다: {OPENAPI_PATH}")
        return 0

    root = args.root.resolve()
    if not root.is_dir():
        print(f"런 루트가 폴더가 아니다: {root}", file=sys.stderr)
        return 1
    database_url = args.database_url if args.database_url is not None else _settings_database_url()
    app = create_app(root=root, database_url=database_url)
    uvicorn.run(app, host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
