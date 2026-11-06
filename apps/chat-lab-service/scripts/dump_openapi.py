"""서비스 HTTP 스키마를 `apps/chat-lab/service-openapi.json` 에 떨군다 — 웹이 그 파일로 타입을 만든다.

`apps/chat-lab-service` 에서 `uv run python scripts/dump_openapi.py`. 라우트·응답 모델을 고쳤으면 다시 떨궈 함께 커밋한다.
"""

from pathlib import Path

from chat_lab_service.openapi import openapi_text

TARGET = Path(__file__).resolve().parents[2] / "chat-lab" / "service-openapi.json"


def main() -> None:
    TARGET.write_bytes(openapi_text().encode("utf-8"))


if __name__ == "__main__":
    main()
