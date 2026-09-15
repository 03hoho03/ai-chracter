"""Discord 웹훅 알림 + healthchecks.io ping — 공통 stdlib 유틸(monitoring-techspec.md MT-10).

`backup_db.py`·`check_resources.py`가 여기에 얹는다. **stdlib(`urllib.request`)만 쓴다** —
`requests`/`httpx`를 쓰면 프로덕션 크론의 시스템 python3(boto3만 설치돼 있음)에서 import
시점에 죽는다. `tests/test_ops_production_cron_importable.py`가 이 파일 자신의 최상단
import도 직접 검사한다.

**두 함수 모두 예외를 던지지 않는다.** 알림·ping은 부가 기능이라, 웹훅 URL 오타나 네트워크
일시 장애 같은 알림 자체의 실패가 백업·리소스 감시 같은 본 작업을 실패로 만들면 안 된다 —
"알림이 안 갔다"와 "백업이 안 됐다"는 서로 다른 사고이고, 후자만 크론을 죽여야 한다.
"""

import http.client
import json
import os
import urllib.error
import urllib.request

_TIMEOUT_SECONDS = 10


def _fire(url: str, *, data: bytes | None = None) -> bool:
    """`url`을 호출한다(`data`가 있으면 JSON POST, 없으면 GET). 실패해도 예외를 던지지 않는다.

    `Request()` 생성도 `try` 안에 있다 — 스킴 없는 URL은 `urlopen`이 아니라 `Request()` 생성
    시점에 `ValueError`를 던진다. `http.client.InvalidURL`(제어 문자가 섞인 URL)은 `URLError`도
    `OSError`도 `ValueError`도 아니라 따로 잡아야 한다.
    """
    try:
        request = urllib.request.Request(url, data=data)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return bool(200 <= response.status < 300)
    except (urllib.error.URLError, OSError, ValueError, http.client.InvalidURL):
        return False


def notify(message: str) -> bool:
    """`DISCORD_WEBHOOK_URL`이 가리키는 Discord 웹훅으로 `message`를 보낸다.

    `backup_db.py`(R2 용량)·`check_resources.py`(메모리·디스크)가 같은 채널로 함께 쏜다 —
    두 번째 웹훅이 필요해지면 그때 인자로 뺀다. URL이 설정돼 있지 않으면 조용히 건너뛰고
    `True`를 돌려준다 — 알림 미설정은 실패가 아니다.
    """
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return True
    return _fire(url, data=json.dumps({"content": message}).encode())


def ping(url: str) -> bool:
    """healthchecks.io 같은 dead-man's-switch URL을 GET으로 호출한다(check-in).

    `notify`와 달리 완성된 URL을 인자로 받는다 — 호출부(`backup_db.py`)가 start/성공/실패
    세 지점마다 다른 접미사(`/start`·`/fail`)를 붙인 URL을 만들어 넘기기 때문이다.
    """
    return _fire(url)
