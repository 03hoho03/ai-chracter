"""측정 서버가 URL 로 받은 묶음 id 를 파일 경로로 되돌리는 규칙.

id 는 런 루트 기준 상대 경로를 base64url 로 감싼 것이라 누구나 만들어 보낼 수 있다. 되돌린 경로가 루트 밖이나 링크를
가리키면 측정 서버가 런 폴더 밖의 파일을 읽어 응답에 싣게 되므로, 되돌리는 쪽이 모양을 엄격히 본다."""

import base64
from pathlib import Path

import pytest

from chat_lab.run_id import RunIdError, decode_run_id, encode_run_id


def _id_of(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_run_id_is_one_url_segment_and_decodes_back_to_the_same_file(tmp_path: Path) -> None:
    """`/` 가 남으면 URL 인코딩한 `%2F` 를 서버가 풀어 라우팅이 깨지므로 id 는 한 마디여야 하고, 되돌리면 같은 파일이어야
    목록에서 고른 묶음과 상세가 같은 묶음이다."""
    log = tmp_path / "runs" / "a b" / "chat.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("", encoding="utf-8")

    run_id = encode_run_id(tmp_path, log)

    assert "/" not in run_id and "=" not in run_id and "%" not in run_id
    assert decode_run_id(tmp_path, run_id) == log.resolve()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("../outside.jsonl", id="parent"),
        pytest.param("a/../chat.jsonl", id="parent-inside-root"),
        pytest.param("/etc/passwd", id="absolute"),
        pytest.param("./chat.jsonl", id="dot-segment"),
        pytest.param("a//chat.jsonl", id="empty-segment"),
        pytest.param("a\x00b.jsonl", id="nul"),
        pytest.param("", id="empty"),
    ],
)
def test_run_id_refuses_paths_that_are_not_a_plain_relative_path(tmp_path: Path, text: str) -> None:
    """`..` 는 루트 안으로 되돌아와도 거부한다 — 같은 파일을 가리키는 id 가 여럿이면 id 로 묶음을 가를 수 없고, 상위로
    올라가는 모양을 허용하는 순간 resolve 확인 하나에만 기대게 된다. 절대 경로·빈 마디·NUL 도 같은 이유로 거부한다."""
    (tmp_path / "a").mkdir()
    (tmp_path / "chat.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(RunIdError):
        decode_run_id(tmp_path, _id_of(text))


def test_run_id_refuses_text_that_is_not_base64url(tmp_path: Path) -> None:
    """id 를 손으로 고친 요청이 디코드 예외로 500 이 되지 않고 거부로 끝나야 한다."""
    with pytest.raises(RunIdError):
        decode_run_id(tmp_path, "@@@")
    with pytest.raises(RunIdError):
        decode_run_id(tmp_path, base64.urlsafe_b64encode(b"\xff\xfe").decode())


def test_run_id_refuses_a_symlinked_file_or_folder_even_inside_the_root(tmp_path: Path) -> None:
    """링크는 가리키는 곳이 바뀌어도 id 가 그대로라, 루트 안의 링크라도 읽지 않는다. 폴더 링크는 resolve 뒤 루트 밖으로 나가는
    가장 쉬운 길이다."""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "chat.jsonl").write_text("", encoding="utf-8")
    (root / "real.jsonl").write_text("", encoding="utf-8")
    (root / "link.jsonl").symlink_to(root / "real.jsonl")
    (root / "linked-dir").symlink_to(outside)

    with pytest.raises(RunIdError):
        decode_run_id(root, _id_of("link.jsonl"))
    with pytest.raises(RunIdError):
        decode_run_id(root, _id_of("linked-dir/chat.jsonl"))
    assert decode_run_id(root, _id_of("real.jsonl")) == (root / "real.jsonl").resolve()
