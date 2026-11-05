"""일일 운영 요약 래퍼(`ops/daily-digest.sh`)의 Discord 알림.

    # 요약: 표준입력을 머리 줄마다 나눠 한 통씩 보낸다
    printf '%s\\n' "$output" | PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.daily_digest_notify
    # 실패 고정 문구: 인자를 이어 한 통으로 보낸다
    PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.daily_digest_notify "<문구>"

요약 자체는 api 컨테이너 안에서 만들어지고(`python -m api.ops_digest`) 이미 한 통이 Discord 상한 안에 들도록 나뉘어 나온다. 이 모듈은
표준입력에서 `MESSAGE_HEADER` 로 시작하는 줄마다 새 통을 시작해 순서대로 보내고, 첫 머리 앞의 줄은 버린다. `--dry-run` 출력은 머리
앞에 `[dry-run] ` 이 붙어 머리 줄이 없으므로 아무것도 보내지 않는다.

`MESSAGE_HEADER` 는 앱 모듈(`api.ops_digest.report`)의 같은 이름 상수의 사본이다 — 시스템 python3 에는 `api` 패키지가 없어 import
할 수 없다. 둘이 같은지는 테스트가 본다. stdlib 과 `ops.notify` 만 쓴다(`tests/test_ops_production_cron_importable.py`).
"""

import sys

from ops.notify import notify

MESSAGE_HEADER = "📊 일일 운영 요약"


def split_messages(text: str) -> list[str]:
    """머리 줄마다 한 통. 첫 머리 앞의 줄은 버리고, 통마다 앞뒤 빈 줄을 걷는다."""
    messages: list[list[str]] = []
    for line in text.splitlines():
        if line.startswith(MESSAGE_HEADER):
            messages.append([line])
        elif messages:
            messages[-1].append(line)
    return ["\n".join(lines).strip() for lines in messages]


def main(argv: list[str]) -> int:
    if argv:
        message = " ".join(argv).strip()
        if message:
            notify(message)
        return 0
    # 알림이 안 간 것은 요약 실패가 아니다 — `notify` 는 예외를 던지지 않고, 여기서도 종료 코드를 바꾸지 않는다.
    for message in split_messages(sys.stdin.read()):
        notify(message)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
