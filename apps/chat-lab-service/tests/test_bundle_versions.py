"""판 쓰기·꺼내기·목록·삭제·되살림.

판 키는 압축 푼 JSON 바이트의 sha256 이다. 같은 내용은 한 판이고, 판 번호는 처음 들어온 순서로 매기며 지운 판도 번호를
차지한다. 최신 판은 그 런의 지우지 않은 판 가운데 가장 늦게 처음 들어온 것이다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import pytest

from bundles import (
    COMMIT_A,
    COMMIT_B,
    gz,
    make_bundle,
    post_upload,
    provenance,
    sha256_hex,
    to_json,
    upload_bundle,
    upload_header,
)
from harness import Db, Lab, assert_error, assert_security_headers
from keys import READER_EMAIL, SECOND_UPLOADER_ID, UPLOADER_ID, auth, human_token, service_token

RUN = "run-versions"
OTHER_RUN = "run-other"

VERSION_FIELDS = {
    "sha256",
    "versionNumber",
    "uploadedAt",
    "uploadedBy",
    "raw",
    "contractVersion",
    "sourceCommit",
    "provenance",
    "compressedSize",
    "uncompressedSize",
}


def reader() -> dict[str, str]:
    return auth(human_token(READER_EMAIL))


async def list_runs(lab: Lab) -> list[dict[str, Any]]:
    response = await lab.client.get("/api/runs", headers=reader())
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def versions_of(lab: Lab, run_id: str) -> list[dict[str, Any]]:
    response = await lab.client.get(f"/api/runs/{run_id}/versions", headers=reader())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runId"] == run_id
    versions: list[dict[str, Any]] = body["versions"]
    return versions


async def download(
    lab: Lab, run_id: str, sha: str, *, accept_encoding: str, method: str = "GET"
) -> tuple[httpx.Response, bytes]:
    """응답과 전송된 바이트 그대로(httpx 의 gzip 자동 풀기를 거치지 않은 것)를 돌려준다.

    200 이 아니면 본문을 읽어 응답에 남긴다 — 스트림으로 모은 바이트는 응답에 캐시되지 않아, 그대로 두면 거부 응답을 단언하는
    `.json()` 이 서버 응답과 무관하게 `ResponseNotRead` 로 깨진다. 거부 응답은 JSON 오류라 압축이 없어 읽은 본문이 보낸 바이트다.
    """
    headers = {**reader(), "Accept-Encoding": accept_encoding}
    url = f"/api/runs/{run_id}/versions/{sha}/bundle"
    async with lab.client.stream(method, url, headers=headers) as response:
        if response.status_code != 200:
            await response.aread()
            return response, response.content
        raw = b"".join([chunk async for chunk in response.aiter_raw()])
    return response, raw


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def test_upload_response_shape(lab: Lab) -> None:
    response, data, _ = await upload_bundle(lab.client, make_bundle(RUN))
    assert response.status_code == 201
    assert response.json() == {"runId": RUN, "sha256": sha256_hex(data), "status": "created", "versionNumber": 1}
    assert response.headers["cache-control"] == "no-store"
    assert_security_headers(response)


@pytest.mark.parametrize("raw", [True, False], ids=["raw", "redacted"])
async def test_round_trip_keeps_sha_for_raw_and_redacted(lab: Lab, raw: bool) -> None:
    response, data, compressed = await upload_bundle(lab.client, make_bundle(RUN, raw=raw))
    sha = response.json()["sha256"]
    assert sha == sha256_hex(data)
    _, served_gzip = await download(lab, RUN, sha, accept_encoding="gzip")
    assert served_gzip == compressed
    _, served_plain = await download(lab, RUN, sha, accept_encoding="identity")
    assert served_plain == data
    assert sha256_hex(served_plain) == sha


async def test_returned_sha_matches_measured_sha(lab: Lab) -> None:
    # 서비스는 JSON 을 다시 직렬화하지 않는다 — 들여쓰기·칸 순서가 다른 바이트도 그 바이트의 sha 가 판 키다.
    data = to_json(make_bundle(RUN), indent=1)
    compressed = gz(data, level=9)
    response = await post_upload(lab.client, RUN, compressed)
    assert response.status_code == 201, response.text
    sha = response.json()["sha256"]
    assert sha == sha256_hex(data)
    assert sha != sha256_hex(compressed)
    _, served_plain = await download(lab, RUN, sha, accept_encoding="identity")
    assert served_plain == data


async def test_list_marks_raw(lab: Lab) -> None:
    await upload_bundle(lab.client, make_bundle(RUN, raw=True))
    lab.clock.advance(minutes=1)
    await upload_bundle(lab.client, make_bundle(OTHER_RUN, raw=False))
    items = {item["runId"]: item for item in await list_runs(lab)}
    assert items[RUN]["latest"]["raw"] is True
    assert items[OTHER_RUN]["latest"]["raw"] is False
    assert (await versions_of(lab, RUN))[0]["raw"] is True


async def test_list_item_shape(lab: Lab) -> None:
    bundle = make_bundle(RUN)
    response, data, compressed = await upload_bundle(lab.client, bundle)
    assert response.status_code == 201
    [item] = await list_runs(lab)
    assert set(item) == {"runId", "latest", "versionCount", "run"}
    assert item["runId"] == RUN
    assert item["run"] == bundle["detail"]["run"]
    latest = item["latest"]
    assert set(latest) == VERSION_FIELDS
    assert latest["sha256"] == sha256_hex(data)
    assert latest["versionNumber"] == 1
    assert at(latest["uploadedAt"]) == lab.clock.now
    assert latest["uploadedBy"] == UPLOADER_ID
    assert latest["contractVersion"] == 1
    assert latest["sourceCommit"] == {"commit": COMMIT_A, "dirty": False}
    assert latest["provenance"] == provenance()
    assert (latest["compressedSize"], latest["uncompressedSize"]) == (len(compressed), len(data))
    versions = await versions_of(lab, RUN)
    assert item["versionCount"] == len(versions) == 1
    assert versions[0] == latest


async def test_gzip_served_as_is_with_no_store(lab: Lab) -> None:
    response, _, compressed = await upload_bundle(lab.client, make_bundle(RUN))
    sha = response.json()["sha256"]
    served, raw = await download(lab, RUN, sha, accept_encoding="gzip")
    assert served.status_code == 200
    assert raw == compressed
    assert served.headers["content-encoding"] == "gzip"
    assert served.headers["content-type"].startswith("application/json")
    assert "accept-encoding" in served.headers.get("vary", "").lower()
    assert served.headers["cache-control"] == "no-store"
    assert_security_headers(served)


@pytest.mark.parametrize("accept_encoding", ["identity", "br", "deflate"])
async def test_plain_client_gets_decompressed_body(lab: Lab, accept_encoding: str) -> None:
    response, data, _ = await upload_bundle(lab.client, make_bundle(RUN))
    sha = response.json()["sha256"]
    served, raw = await download(lab, RUN, sha, accept_encoding=accept_encoding)
    assert served.status_code == 200
    assert raw == data
    assert served.headers.get("content-encoding", "identity") == "identity"
    assert served.headers["content-type"].startswith("application/json")
    assert "accept-encoding" in served.headers.get("vary", "").lower()
    assert served.headers["cache-control"] == "no-store"


async def test_head_bundle_sends_headers_only(lab: Lab) -> None:
    response, _, _ = await upload_bundle(lab.client, make_bundle(RUN))
    sha = response.json()["sha256"]
    served, raw = await download(lab, RUN, sha, accept_encoding="gzip", method="HEAD")
    assert served.status_code == 200
    assert raw == b""
    assert served.headers["content-encoding"] == "gzip"
    assert served.headers["cache-control"] == "no-store"


async def test_same_content_twice_is_one_version_even_with_other_commit(lab: Lab, db: Db) -> None:
    bundle = make_bundle(RUN)
    data = to_json(bundle)
    first_gzip = gz(data, level=6)
    first = await post_upload(lab.client, RUN, first_gzip)
    assert first.status_code == 201
    first_time = lab.clock.now
    lab.clock.advance(minutes=5)
    # 같은 JSON 을 다른 압축 수준(다른 gzip 바이트)·다른 커밋·다른 올리는 이로 다시 올린다.
    second = await post_upload(
        lab.client,
        RUN,
        gz(data, level=1),
        token=service_token(SECOND_UPLOADER_ID),
        header=upload_header(commit=COMMIT_B, dirty=True),
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"runId": RUN, "sha256": sha256_hex(data), "status": "exists", "versionNumber": 1}
    [version] = await versions_of(lab, RUN)
    assert version["sourceCommit"] == {"commit": COMMIT_A, "dirty": False}
    assert version["uploadedBy"] == UPLOADER_ID
    assert at(version["uploadedAt"]) == first_time
    _, served = await download(lab, RUN, sha256_hex(data), accept_encoding="gzip")
    assert served == first_gzip
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 1


async def test_changed_content_is_version_two_and_latest(lab: Lab) -> None:
    _, first_data, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=0))
    first_time = lab.clock.now
    lab.clock.advance(minutes=1)
    second, second_data, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=1))
    assert second.status_code == 201
    assert second.json()["versionNumber"] == 2
    [item] = await list_runs(lab)
    assert item["latest"]["sha256"] == sha256_hex(second_data)
    assert item["latest"]["versionNumber"] == 2
    versions = await versions_of(lab, RUN)
    assert item["versionCount"] == len(versions) == 2
    assert [(v["versionNumber"], v["sha256"]) for v in versions] == [
        (2, sha256_hex(second_data)),
        (1, sha256_hex(first_data)),
    ]
    assert [at(v["uploadedAt"]) for v in versions] == [lab.clock.now, first_time]


async def test_reuploading_older_content_keeps_newer_latest(lab: Lab) -> None:
    # A → B → A(같은 바이트)면 세 번째는 "이미 있음"이라 새 판이 생기지 않고 최신은 B 로 남는다.
    _, a_data, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=0))
    lab.clock.advance(minutes=1)
    _, b_data, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=1))
    lab.clock.advance(minutes=1)
    again, _, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=0))
    assert again.json()["status"] == "exists"
    assert again.json()["versionNumber"] == 1
    [item] = await list_runs(lab)
    assert item["latest"]["sha256"] == sha256_hex(b_data)
    assert len(await versions_of(lab, RUN)) == 2
    assert sha256_hex(a_data) != sha256_hex(b_data)


async def test_list_orders_runs_by_latest_upload_desc(lab: Lab) -> None:
    await upload_bundle(lab.client, make_bundle(RUN))
    lab.clock.advance(minutes=1)
    await upload_bundle(lab.client, make_bundle(OTHER_RUN))
    assert [item["runId"] for item in await list_runs(lab)] == [OTHER_RUN, RUN]
    lab.clock.advance(minutes=1)
    await upload_bundle(lab.client, make_bundle(RUN, variant=1))
    assert [item["runId"] for item in await list_runs(lab)] == [RUN, OTHER_RUN]


async def test_delete_hides_run_and_clears_body(lab: Lab, db: Db) -> None:
    first, _, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=0))
    second, _, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=1))
    await upload_bundle(lab.client, make_bundle(OTHER_RUN))
    lab.clock.advance(hours=1)
    response = await lab.client.request("DELETE", f"/api/runs/{RUN}", json={"runId": RUN}, headers=reader())
    assert response.status_code == 200, response.text
    assert response.json() == {"runId": RUN, "deletedVersions": 2}
    assert response.headers["cache-control"] == "no-store"

    assert [item["runId"] for item in await list_runs(lab)] == [OTHER_RUN]
    assert_error(await lab.client.get(f"/api/runs/{RUN}/versions", headers=reader()), 404, "notFound")
    for uploaded in (first, second):
        for encoding in ("gzip", "identity"):
            served, _ = await download(lab, RUN, uploaded.json()["sha256"], accept_encoding=encoding)
            assert_error(served, 404, "notFound")

    rows = await db.fetch(
        "SELECT body IS NULL AS cleared, deleted_by, deleted_at FROM bundle_versions WHERE run_id = :run ORDER BY id",
        run=RUN,
    )
    assert rows == [
        {"cleared": True, "deleted_by": READER_EMAIL, "deleted_at": lab.clock.now},
        {"cleared": True, "deleted_by": READER_EMAIL, "deleted_at": lab.clock.now},
    ]
    other = await db.fetch("SELECT body IS NULL AS cleared FROM bundle_versions WHERE run_id = :run", run=OTHER_RUN)
    assert other == [{"cleared": False}]

    again = await lab.client.request("DELETE", f"/api/runs/{RUN}", json={"runId": RUN}, headers=reader())
    assert_error(again, 404, "notFound")


async def test_reupload_after_delete_restores(lab: Lab, db: Db) -> None:
    _, a_data, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=0))
    lab.clock.advance(minutes=1)
    _, b_data, _ = await upload_bundle(lab.client, make_bundle(RUN, variant=1))
    lab.clock.advance(minutes=1)
    deleted = await lab.client.request("DELETE", f"/api/runs/{RUN}", json={"runId": RUN}, headers=reader())
    assert deleted.status_code == 200

    lab.clock.advance(minutes=1)
    restored = await post_upload(
        lab.client,
        RUN,
        gz(a_data),
        token=service_token(SECOND_UPLOADER_ID),
        header=upload_header(commit=COMMIT_B),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json() == {"runId": RUN, "sha256": sha256_hex(a_data), "status": "restored", "versionNumber": 1}
    # 되살림은 새로 올린 것과 같다 — 올린 이·때·만든 커밋은 이번 값이고, 판 번호는 처음 들어온 자리 그대로다.
    [item] = await list_runs(lab)
    assert item["versionCount"] == 1
    latest = item["latest"]
    assert (latest["sha256"], latest["versionNumber"]) == (sha256_hex(a_data), 1)
    assert latest["sourceCommit"]["commit"] == COMMIT_B
    assert latest["uploadedBy"] == SECOND_UPLOADER_ID
    assert at(latest["uploadedAt"]) == lab.clock.now
    rows = await db.fetch(
        "SELECT body IS NOT NULL AS has_body, deleted_by, deleted_at FROM bundle_versions WHERE sha256 = :sha",
        sha=sha256_hex(a_data),
    )
    assert rows == [{"has_body": True, "deleted_by": None, "deleted_at": None}]
    _, served = await download(lab, RUN, sha256_hex(a_data), accept_encoding="identity")
    assert served == a_data

    lab.clock.advance(minutes=1)
    again = await post_upload(lab.client, RUN, gz(b_data))
    assert again.json()["status"] == "restored"
    assert again.json()["versionNumber"] == 2
    [item] = await list_runs(lab)
    assert item["latest"]["sha256"] == sha256_hex(b_data)
    assert item["versionCount"] == 2


async def test_concurrent_identical_uploads_make_one_row(lab: Lab, db: Db) -> None:
    data = to_json(make_bundle(RUN))
    compressed = gz(data)
    responses = await asyncio.gather(*(post_upload(lab.client, RUN, compressed) for _ in range(4)))
    statuses = sorted((r.status_code, r.json()["status"]) for r in responses)
    assert statuses == [(200, "exists"), (200, "exists"), (200, "exists"), (201, "created")]
    assert {r.json()["versionNumber"] for r in responses} == {1}
    assert await db.scalar("SELECT count(*) FROM bundle_versions") == 1


async def test_bundle_of_other_run_is_404(lab: Lab) -> None:
    response, _, _ = await upload_bundle(lab.client, make_bundle(RUN))
    await upload_bundle(lab.client, make_bundle(OTHER_RUN))
    served, _ = await download(lab, OTHER_RUN, response.json()["sha256"], accept_encoding="identity")
    assert_error(served, 404, "notFound")


async def test_unknown_version_is_404(lab: Lab) -> None:
    await upload_bundle(lab.client, make_bundle(RUN))
    served, _ = await download(lab, RUN, "0" * 64, accept_encoding="gzip")
    assert_error(served, 404, "notFound")


async def test_database_error_is_503_without_details(lab: Lab, db: Db) -> None:
    await upload_bundle(lab.client, make_bundle(RUN))
    await db.execute("ALTER TABLE bundle_versions RENAME TO bundle_versions_moved_away")
    try:
        response = await lab.client.get("/api/runs", headers=reader())
    finally:
        await db.execute("ALTER TABLE bundle_versions_moved_away RENAME TO bundle_versions")
    body = assert_error(response, 503, "dbUnavailable")
    assert "bundle_versions" not in body["detail"]
    assert "SELECT" not in body["detail"].upper()
    assert (await db.last_access_row())["reason"] == "dbUnavailable"


@pytest.mark.parametrize(
    ("accept_encoding", "gzipped"),
    [
        ("gzip;q=0", False),
        ("gzip;q=0, *", False),
        ("*, gzip;q=0", False),
        ("*", True),
        ("*;q=0", False),
        ("GZIP", True),
        ("deflate, gzip;q=0.5", True),
        ("", False),
    ],
    ids=[
        "gzip-q0",
        "gzip-q0-then-star",
        "star-then-gzip-q0",
        "star",
        "star-q0",
        "uppercase",
        "gzip-lower-quality",
        "empty",
    ],
)
async def test_accept_encoding_negotiation(lab: Lab, accept_encoding: str, gzipped: bool) -> None:
    # `q=0` 은 거절이고, 이름이 따로 없으면 `*` 를 따른다 — 모든 코딩을 받는다는 `*` 에는 저장한 gzip 을 그대로 준다. 이름을
    # 적은 거절(`gzip;q=0`)은 `*` 보다 앞선다.
    response, data, compressed = await upload_bundle(lab.client, make_bundle(RUN))
    served, raw = await download(lab, RUN, response.json()["sha256"], accept_encoding=accept_encoding)
    assert served.status_code == 200
    if gzipped:
        assert served.headers.get("content-encoding") == "gzip"
        assert raw == compressed
    else:
        assert "content-encoding" not in served.headers
        assert raw == data
    assert "accept-encoding" in served.headers.get("vary", "").lower()


async def test_head_without_gzip_reports_uncompressed_length(lab: Lab, db: Db) -> None:
    # 풀어서 보낼 응답의 HEAD 는 본문 없이 푼 크기를 길이로 알린다. 본문을 내주지 않았으므로 원문 묶음이어도 내줌 표지가 없다.
    response, data, compressed = await upload_bundle(lab.client, make_bundle(RUN, raw=True))
    sha = response.json()["sha256"]
    url = f"/api/runs/{RUN}/versions/{sha}/bundle"
    head = await lab.client.head(url, headers={**reader(), "Accept-Encoding": "identity"})
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(data))
    assert "content-encoding" not in head.headers
    assert (await db.last_access_row())["raw_served"] is False

    head_gzip = await lab.client.head(url, headers={**reader(), "Accept-Encoding": "gzip"})
    assert head_gzip.headers["content-length"] == str(len(compressed))
    assert (await db.last_access_row())["raw_served"] is False

    served, raw = await download(lab, RUN, sha, accept_encoding="identity")
    assert served.headers["content-length"] == str(len(data)) == str(len(raw))
    assert (await db.last_access_row())["raw_served"] is True


# 시험 쪽 문 — 서비스가 쓸 수 있는 정수 하나짜리 advisory 잠금(`hashtext` 등 int4 범위)과 겹치지 않게 int4 밖 값을 쓴다.
_GATE_KEY = 2**40 + 7
_HOLD_FUNCTION = "lab_test_hold_insert"


async def _advisory_waiters(db: Db) -> int:
    count: int = await db.scalar(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock' AND wait_event = 'advisory'"
    )
    return count


async def _wait_for(condition: Any, what: str) -> None:
    # 요청이 DB 에서 멈춘 자리에 닿을 때까지 기다린다(시간 판정에 쓰지 않는다).
    for _ in range(500):
        if await condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"{what} 에 닿지 않았다")


async def test_concurrent_different_uploads_get_distinct_version_numbers(lab: Lab, db: Db) -> None:
    # 같은 런에 다른 내용 둘을 동시에 올린다. 첫 올리기가 판 행을 넣고 커밋하기 전에 멈춘 사이 둘째가 끝나도, 두 응답의 판
    # 번호는 겹치지 않고 목록이 매기는 번호와 같아야 한다. 첫 올리기를 멈추는 문은 그 내용의 행에만 걸리는 시험용 트리거다 — 서비스가
    # 어떤 방법으로 순서를 지키는지와 무관하게, "넣었지만 아직 커밋하지 않은 행"을 만든다.
    first_data = to_json(make_bundle(RUN, variant=0))
    second_data = to_json(make_bundle(RUN, variant=1))
    first_sha = sha256_hex(first_data)
    await db.execute(
        f"CREATE FUNCTION {_HOLD_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        f"IF NEW.sha256 = '{first_sha}' THEN PERFORM pg_advisory_xact_lock_shared({_GATE_KEY}); END IF; "
        "RETURN NEW; END $$"
    )
    await db.execute(
        f"CREATE TRIGGER {_HOLD_FUNCTION} AFTER INSERT ON bundle_versions "
        f"FOR EACH ROW EXECUTE FUNCTION {_HOLD_FUNCTION}()"
    )
    tasks: list[asyncio.Task[httpx.Response]] = []
    try:
        async with db.engine.connect() as gate:
            await gate.exec_driver_sql(f"SELECT pg_advisory_lock({_GATE_KEY})")
            try:
                first = asyncio.create_task(post_upload(lab.client, RUN, gz(first_data)))
                tasks.append(first)

                async def first_is_held() -> bool:
                    return await _advisory_waiters(db) >= 1

                await _wait_for(first_is_held, "첫 올리기가 커밋 전")
                second = asyncio.create_task(post_upload(lab.client, RUN, gz(second_data)))
                tasks.append(second)

                async def second_settled() -> bool:
                    return second.done() or await _advisory_waiters(db) >= 2

                await _wait_for(second_settled, "둘째 올리기가 끝나거나 기다리는 자리")
            finally:
                await gate.exec_driver_sql(f"SELECT pg_advisory_unlock({_GATE_KEY})")
        responses = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await db.execute(f"DROP TRIGGER IF EXISTS {_HOLD_FUNCTION} ON bundle_versions")
        await db.execute(f"DROP FUNCTION IF EXISTS {_HOLD_FUNCTION}()")

    assert [response.status_code for response in responses] == [201, 201], [r.text for r in responses]
    numbers = {response.json()["sha256"]: response.json()["versionNumber"] for response in responses}
    assert sorted(numbers.values()) == [1, 2], numbers
    listed = {version["sha256"]: version["versionNumber"] for version in await versions_of(lab, RUN)}
    assert listed == numbers
    assert listed[first_sha] == 1
