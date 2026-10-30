"""묶음 id — 런 루트 기준 드라이버 로그의 상대 경로를 base64url 로 감싼 불투명 문자열.

경로를 URL 에 그대로 실으면 `/` 를 `%2F` 로 인코딩해도 서버가 풀어 라우팅이 깨지므로 한 마디로 감싼다. id 는 누구나 만들어
보낼 수 있으므로 되돌릴 때 모양을 엄격히 본다: 정규형 상대 경로만 받고(`..`·`.`·빈 마디·절대 경로·NUL 거부), 루트 아래
마디 가운데 링크가 하나라도 있으면 거부하고, resolve 한 결과가 루트 안인지 다시 본다."""

import base64
import binascii
from pathlib import Path, PurePosixPath


class RunIdError(ValueError):
    """묶음 id 를 받지 않는다 — 측정 서버는 이것을 404 로 낸다(어느 모양이 거부됐는지 알려 줄 이유가 없다)."""


def encode_run_id(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return base64.urlsafe_b64encode(relative.encode()).decode().rstrip("=")


def decode_run_id(root: Path, run_id: str) -> Path:
    """id 가 가리키는 루트 안 경로(resolve 한 것). 파일이 있는지는 보지 않는다 — 부르는 쪽이 찾은 묶음과 대조한다."""
    try:
        text = base64.urlsafe_b64decode(run_id + "=" * (-len(run_id) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise RunIdError("묶음 id 가 base64url 이 아니다") from error
    if not text or "\x00" in text:
        raise RunIdError("묶음 id 의 경로가 비었거나 NUL 이 있다")
    relative = PurePosixPath(text)
    if relative.is_absolute() or str(relative) != text or ".." in relative.parts:
        raise RunIdError("묶음 id 는 정규형 상대 경로만 받는다")
    base = root.resolve()
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RunIdError("묶음 id 의 경로에 링크가 있다")
    resolved = current.resolve()
    if not resolved.is_relative_to(base):
        raise RunIdError("묶음 id 가 루트 밖을 가리킨다")
    return resolved
