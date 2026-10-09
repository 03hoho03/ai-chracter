"""크리에이터 정산 월 확정 래퍼(`ops/creator-payout-settle.sh`)의 Discord 알림.

    PYTHONPATH=/opt/ddona/scripts /usr/bin/python3 -m ops.creator_payout_notify "<문구>"

월 확정 자체는 api 컨테이너 안에서 돌고, 이 모듈은 그 결과 문구를 VM 의 시스템 python3 로 보내기만 한다. stdlib 과
`ops.notify` 만 쓴다 — 시스템 python3 에는 앱 의존성이 없다(`tests/test_ops_production_cron_importable.py`).
"""

import sys

from ops.notify import notify


def main(argv: list[str]) -> int:
    message = " ".join(argv).strip()
    if message:
        # 알림이 안 간 것은 월 확정 실패가 아니다 — `notify` 는 예외를 던지지 않고, 여기서도 종료 코드를 바꾸지 않는다.
        notify(message)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
