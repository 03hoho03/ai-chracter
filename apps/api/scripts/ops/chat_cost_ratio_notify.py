"""채팅 원가 비율 래퍼(`ops/chat-cost-ratio.sh`)의 Discord 알림.

    PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.chat_cost_ratio_notify "<문구>"

리포트 자체는 api 컨테이너 안에서 돌고(`python -m api.clover.chat_cost_ratio`), 이 모듈은 그 경보·실패 문구를 VM 의 시스템
python3 로 보내기만 한다. stdlib 과 `ops.notify` 만 쓴다 — 시스템 python3 에는 앱 의존성이 없다
(`tests/test_ops_production_cron_importable.py`).
"""

import sys

from ops.notify import notify


def main(argv: list[str]) -> int:
    message = " ".join(argv).strip()
    if message:
        # 알림이 안 간 것은 리포트 실패가 아니다 — `notify` 는 예외를 던지지 않고, 여기서도 종료 코드를 바꾸지 않는다.
        notify(message)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
