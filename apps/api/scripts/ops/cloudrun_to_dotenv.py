"""Cloud Run 서비스 export(YAML)에서 런타임 env만 뽑아 dotenv 파일로 옮긴다.

**왜 필요한가.** 프로덕션 접속정보(Neon `DATABASE_URL`, Upstash `REDIS_URL`, R2 자격증명)는
`apps/api/.env` 에 없다 — 그 파일은 로컬 개발용이다(localhost DB/Redis). 유일한 소스는 살아 있는
Cloud Run 서비스이고, 그걸 파일로 뜬 게 `~/.config/ddona/cloudrun-env.yaml` 이다.

그 YAML을 그대로 쓰기는 불편하다. 저장소의 다른 스크립트가 전부 `uv run --env-file …` 규약을
쓰므로, 여기서 한 번 dotenv 로 바꿔 두면 이후는 전부 같은 방식으로 돌아간다.

    gcloud --configuration=default run services describe ai-character-chat-api \\
        --region asia-southeast1 --format=export > ~/.config/ddona/cloudrun-env.yaml
    uv run python -m ops.cloudrun_to_dotenv    # → ~/.config/ddona/prod.env (0600)

    # 이후 사용
    uv run --env-file ~/.config/ddona/prod.env python -m ops.backup_db

**출력 파일에는 비밀값이 평문으로 들어간다.** 그래서 저장소 밖(`~/.config/ddona`)에 쓰고 0600 으로
잠근다. 저장소 안에 만들지 않는 게 이 스크립트의 핵심 제약이다.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SOURCE = Path.home() / ".config" / "ddona" / "cloudrun-env.yaml"
DEFAULT_TARGET = Path.home() / ".config" / "ddona" / "prod.env"


def extract_env(service: dict[str, Any]) -> dict[str, str]:
    """Knative 형식 export 에서 첫 컨테이너의 env 이름/값 쌍을 꺼낸다.

    `valueFrom`(Secret Manager 참조)으로 들어온 항목은 값이 여기 없으므로 건너뛰고 경고한다 —
    조용히 빠지면 나중에 "env 를 다 옮겼는데 앱이 안 뜬다"가 된다.
    """
    containers = service["spec"]["template"]["spec"]["containers"]
    result: dict[str, str] = {}
    for entry in containers[0].get("env", []):
        name = entry["name"]
        if "value" not in entry:
            print(f"⚠ {name}: 값이 export 에 없다(Secret Manager 참조). 손으로 채워야 한다.", file=sys.stderr)
            continue
        result[name] = str(entry["value"])
    return result


def to_dotenv(env: dict[str, str]) -> str:
    """dotenv 한 줄씩. 값을 통째로 작은따옴표로 감싸 JSON·URL 안의 특수문자를 지킨다.

    `CORS_ALLOW_ORIGINS` 가 `["https://a","https://b"]` 라는 **JSON 배열 문자열**이라 따옴표가
    깨지면 pydantic-settings 파싱이 기동 시점에 실패한다. 값 안의 작은따옴표는 dotenv 관례대로
    `'\\''` 로 탈출한다.
    """
    lines = []
    for name in sorted(env):
        escaped = env[name].replace("'", "'\\''")
        lines.append(f"{name}='{escaped}'")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"export 파일이 없다: {args.source}", file=sys.stderr)
        return 1

    env = extract_env(yaml.safe_load(args.source.read_text()))

    args.target.parent.mkdir(parents=True, exist_ok=True)
    # 파일을 만들기 *전에* 0600 으로 열어야 한다 — 먼저 쓰고 chmod 하면 그 사이에 남이 읽을 수 있다.
    fd = os.open(args.target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(to_dotenv(env))

    print(f"✅ {len(env)}개 env → {args.target} (0600)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
