"""`ops/prune_api_images.py` — 배포가 끝날 때 VM 로컬 API 이미지를 최근 몇 개만 남기고 지운다.

docker CLI 호출은 `subprocess.run` 스텁(`_FakeDocker`)으로 대체한다. 스텁은 이미지·태그·실행 중
컨테이너를 들고 있다가 `docker rmi` 를 받으면 실제로 그 태그를 떼어, 테스트가 "무엇이 남았나" 로
결과를 본다. 실제 도커에서의 동작(실행 중 이미지 삭제 거부 등)은 로컬 도커로 따로 확인했다.
"""

import subprocess
from dataclasses import dataclass, field

import pytest

import ops.prune_api_images as prune_api_images

REPO = "asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api"
OTHER_REPO = "caddy"


def _id(n: int) -> str:
    return "sha256:" + f"{n:x}" * 64


@dataclass
class _Image:
    created: str
    refs: list[tuple[str, str]]  # (저장소, 태그) — 태그 `<none>` 은 태그 잃은 행


@dataclass
class _FakeDocker:
    images: dict[str, _Image]
    running: list[str] = field(default_factory=list)  # 실행 중 컨테이너가 쓰는 이미지 ID
    fail: dict[str, str] = field(default_factory=dict)  # 실패시킬 명령(첫 두 낱말 또는 rmi 대상) → stderr
    calls: list[list[str]] = field(default_factory=list)

    def run(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        assert cmd[0] == "docker"
        key = " ".join(cmd[1:3])
        if key in self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", self.fail[key])
        if cmd[1] == "images":
            # 실제 `docker images REPO` 는 이미 그 저장소로 거르지만, 스크립트가 저장소 열을 다시
            # 확인하는지 보려고 다른 저장소 행도 섞어 돌려준다.
            rows = [f"{repo}\t{image_id}\t{tag}" for image_id, image in self.images.items() for repo, tag in image.refs]
            return subprocess.CompletedProcess(cmd, 0, "\n".join(rows) + "\n", "")
        if cmd[1:3] == ["image", "inspect"]:
            ids = cmd[cmd.index("--format") + 2 :]
            rows = [f"{image_id}\t{self.images[image_id].created}" for image_id in ids]
            return subprocess.CompletedProcess(cmd, 0, "\n".join(rows) + "\n", "")
        if cmd[1] == "ps":
            containers = [f"c{i}" for i in range(len(self.running))]
            return subprocess.CompletedProcess(cmd, 0, "\n".join(containers) + ("\n" if containers else ""), "")
        if cmd[1] == "inspect":
            return subprocess.CompletedProcess(cmd, 0, "\n".join(self.running) + "\n", "")
        if cmd[1] == "rmi":
            assert "-f" not in cmd and "--force" not in cmd
            (target,) = cmd[2:]
            if target in self.fail:
                return subprocess.CompletedProcess(cmd, 1, "", self.fail[target])
            self._remove(target)
            return subprocess.CompletedProcess(cmd, 0, f"Untagged: {target}\n", "")
        raise AssertionError(f"예상 밖 명령: {cmd}")

    def _remove(self, target: str) -> None:
        if target in self.images:
            del self.images[target]
            return
        repo, _, tag = target.rpartition(":")
        for image_id, image in list(self.images.items()):
            if (repo, tag) in image.refs:
                image.refs.remove((repo, tag))
                if not image.refs:
                    del self.images[image_id]
                return
        raise AssertionError(f"없는 대상을 지우려 했다: {target}")

    def remaining_tags(self, repo: str = REPO) -> set[str]:
        return {tag for image in self.images.values() for r, tag in image.refs if r == repo}

    def rmi_targets(self) -> list[str]:
        return [cmd[2] for cmd in self.calls if cmd[1] == "rmi"]


def _five_api_images() -> dict[str, _Image]:
    """t1(가장 오래됨) ~ t5(가장 새것). 생성 시각은 도커가 내는 나노초 UTC 문자열 모양."""
    return {_id(n): _Image(f"2026-10-0{n}T05:39:41.838623127Z", [(REPO, f"t{n}")]) for n in range(1, 6)}


def _install(monkeypatch: pytest.MonkeyPatch, docker: _FakeDocker) -> None:
    monkeypatch.setattr(subprocess, "run", docker.run)


def test_keeps_three_newest_and_removes_the_rest_by_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    docker = _FakeDocker(_five_api_images(), running=[_id(5)])
    _install(monkeypatch, docker)

    failures = prune_api_images.prune(REPO, keep=3)

    assert failures == 0
    assert docker.remaining_tags() == {"t3", "t4", "t5"}
    # 태그 있는 이미지는 ID 가 아니라 `REPO:TAG` 로 지운다 — ID 로 지우면 태그가 여럿인 이미지에서
    # 도커가 강제(-f)를 요구하며 거부한다.
    assert sorted(docker.rmi_targets()) == [f"{REPO}:t1", f"{REPO}:t2"]


def test_keeps_running_image_even_when_it_is_the_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    """손으로 옛 태그로 롤백한 뒤 정리가 돌면 실행 중 이미지가 가장 오래된 것일 수 있다 — 순위와
    무관하게 남기고, 최근 3개도 그대로 남긴다(실행 중 이미지를 3개 안에 넣으려 새 이미지를 지우지 않는다)."""
    docker = _FakeDocker(_five_api_images(), running=[_id(1)])
    _install(monkeypatch, docker)

    assert prune_api_images.prune(REPO, keep=3) == 0

    assert docker.remaining_tags() == {"t1", "t3", "t4", "t5"}
    assert docker.rmi_targets() == [f"{REPO}:t2"]


def test_counts_one_image_with_two_tags_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """`latest` 처럼 같은 이미지에 태그가 둘이면 두 줄로 나온다 — 줄 수로 세면 최근 이미지를 하나 덜 남긴다."""
    images = _five_api_images()
    images[_id(5)].refs.append((REPO, "latest"))
    docker = _FakeDocker(images, running=[_id(5)])
    _install(monkeypatch, docker)

    assert prune_api_images.prune(REPO, keep=3) == 0

    assert docker.remaining_tags() == {"t3", "t4", "t5", "latest"}


def test_removes_every_tag_of_a_doomed_image_one_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    images = _five_api_images()
    images[_id(1)].refs.append((REPO, "old-alias"))
    docker = _FakeDocker(images, running=[_id(5)])
    _install(monkeypatch, docker)

    assert prune_api_images.prune(REPO, keep=3) == 0

    assert _id(1) not in docker.images
    assert f"{REPO}:old-alias" in docker.rmi_targets()
    assert _id(1) not in docker.rmi_targets()


def test_does_not_touch_images_of_other_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    images = _five_api_images()
    images[_id(9)] = _Image("2020-01-01T00:00:00.000000000Z", [(OTHER_REPO, "2-alpine")])
    images[_id(10)] = _Image("2020-01-01T00:00:00.000000000Z", [(OTHER_REPO, "<none>")])
    docker = _FakeDocker(images, running=[_id(5)])
    _install(monkeypatch, docker)

    assert prune_api_images.prune(REPO, keep=3) == 0

    assert _id(9) in docker.images
    assert _id(10) in docker.images
    assert all(target.startswith(f"{REPO}:") for target in docker.rmi_targets())


def test_removes_dangling_rows_of_the_api_repository_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 태그를 다시 받으면 옛 이미지가 태그를 잃고 `REPO <none>` 으로 남는다 — 이건 태그가 없으니 ID 로 지운다.
    순위 3개에는 세지 않는다(롤백 대상이 될 수 없는 이미지다)."""
    images = _five_api_images()
    images[_id(11)] = _Image("2026-10-09T00:00:00.000000000Z", [(REPO, "<none>")])
    docker = _FakeDocker(images, running=[_id(5)])
    _install(monkeypatch, docker)

    assert prune_api_images.prune(REPO, keep=3) == 0

    assert _id(11) not in docker.images
    assert docker.remaining_tags() == {"t3", "t4", "t5"}


def test_continues_after_one_removal_fails_and_reports_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """정지된 컨테이너가 쓰는 이미지처럼 도커가 거부하는 경우 — 나머지는 계속 지우고 실패 수를 돌려준다."""
    docker = _FakeDocker(
        _five_api_images(),
        running=[_id(5)],
        fail={f"{REPO}:t1": "conflict: unable to remove repository reference (must force)"},
    )
    _install(monkeypatch, docker)

    assert prune_api_images.prune(REPO, keep=3) == 1

    assert docker.remaining_tags() == {"t1", "t3", "t4", "t5"}
    assert "must force" in capsys.readouterr().out


@pytest.mark.parametrize("failing", ["images --no-trunc", "ps --quiet", "image inspect"])
def test_removes_nothing_when_a_lookup_fails(monkeypatch: pytest.MonkeyPatch, failing: str) -> None:
    """목록·실행 중 컨테이너·생성 시각 중 하나라도 못 읽으면 무엇을 남겨야 하는지 모른다 — 아무것도 안 지운다."""
    docker = _FakeDocker(_five_api_images(), running=[_id(5)], fail={failing: "Cannot connect to the Docker daemon"})
    _install(monkeypatch, docker)

    with pytest.raises(RuntimeError, match="Docker daemon"):
        prune_api_images.prune(REPO, keep=3)

    assert docker.rmi_targets() == []


def test_main_returns_one_when_any_removal_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    docker = _FakeDocker(_five_api_images(), running=[_id(5)], fail={f"{REPO}:t2": "boom"})
    _install(monkeypatch, docker)
    monkeypatch.setattr("sys.argv", ["prune_api_images.py", "--repo", REPO, "--keep", "3"])

    assert prune_api_images.main() == 1


def test_main_rejects_keep_below_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--keep 0` 이면 실행 중 이미지 하나만 남고 롤백할 곳이 사라진다 — 인자 단계에서 막는다."""
    monkeypatch.setattr("sys.argv", ["prune_api_images.py", "--repo", REPO, "--keep", "0"])

    with pytest.raises(SystemExit):
        prune_api_images.main()
