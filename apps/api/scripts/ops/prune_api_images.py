"""VM 로컬에 쌓인 API 이미지를 최근 몇 개만 남기고 지운다. 배포 워크플로가 끝에서 부른다.

    # 배포 원격 스크립트(.github/workflows/deploy-api.yml)가 실행 이미지 확인 뒤에 부른다
    PYTHONPATH=/opt/ddona/app/apps/api/scripts /usr/bin/python3 -m ops.prune_api_images \\
        --repo asia-northeast3-docker.pkg.dev/ddona-ai-character-chat/ddona/api --keep 3

배포마다 새 SHA 태그 이미지를 받기만 하고 지우지 않아 VM 디스크가 찼다. 그래서:

- **이 저장소의 이미지만** 본다. caddy·postgres 같은 다른 이미지는 건드리지 않는다 — 전역
  `docker image prune` 을 쓰지 않는 이유도 같다(저장소 이름 없는 dangling 은 어느 이미지 것인지 가릴 수 없다).
- 이미지 **ID 단위**로 생성 시각 내림차순 `--keep` 개를 남긴다. 같은 이미지에 태그가 둘이면 두 줄로
  나오므로 줄 수로 세면 하나 덜 남긴다.
- 실행 중 컨테이너가 쓰는 이미지는 순위와 무관하게 남긴다(손 롤백 뒤에는 그게 가장 오래된 것일 수 있다).
- 태그 있는 이미지는 `REPO:TAG` 로 태그마다 지운다. ID 로 지우면 태그가 여럿인 이미지에서 도커가 거부한다.
  **`-f` 는 쓰지 않는다** — `-f` 는 실행 중 이미지의 태그까지 떼어 버리고, 없으면 도커가 사용 중 이미지 삭제를
  한 번 더 거부해 준다.
- 태그를 잃은 이 저장소의 `<none>` 행(같은 태그를 다시 받았을 때 생긴다)은 ID 로 지운다. 롤백 대상이
  될 수 없으므로 남길 개수에 세지 않는다.

남긴 것·지운 것·실패한 것을 한 줄씩 출력한다 — 배포 로그가 곧 기록이다. 삭제 하나가 실패해도 나머지는
계속하고 실패가 있으면 exit 1(배포 워크플로가 경고로 바꾼다). 무엇을 남겨야 할지 판단할 정보(목록·실행 중
컨테이너·생성 시각)를 못 읽으면 아무것도 지우지 않고 exit 1.

⚠️ 크론 모듈과 같은 이유로 stdlib 만 쓴다 — 배포 원격 셸이 VM 의 시스템 `/usr/bin/python3` 로 부른다.
`tests/test_ops_production_cron_importable.py` 가 이 제약을 고정한다.
"""

import argparse
import subprocess
import sys

_NO_TAG = "<none>"


def _docker(args: list[str]) -> str:
    """`docker <args>` 를 돌려 stdout 을 돌려준다. 실패하면 stderr 를 담아 터뜨린다."""
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:2])} 실패:\n{result.stderr.strip()}")
    return result.stdout


def list_repo_images(repo: str) -> dict[str, list[str]]:
    """이 저장소의 이미지 ID → 태그 목록. 태그를 잃은 행은 빈 목록이다."""
    output = _docker(["images", "--no-trunc", "--format", "{{.Repository}}\t{{.ID}}\t{{.Tag}}", repo])
    images: dict[str, list[str]] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        row_repo, image_id, tag = line.split("\t")
        # `docker images REPO` 가 이미 거르지만, 지우는 쪽의 안전장치라 저장소 이름을 한 번 더 본다.
        if row_repo != repo:
            continue
        tags = images.setdefault(image_id, [])
        if tag != _NO_TAG:
            tags.append(tag)
    return images


def running_image_ids() -> set[str]:
    container_ids = _docker(["ps", "--quiet"]).split()
    if not container_ids:
        return set()
    return set(_docker(["inspect", "--format", "{{.Image}}", *container_ids]).split())


def created_at(image_ids: list[str]) -> dict[str, str]:
    """ID → 생성 시각 앞 19자(`YYYY-MM-DDTHH:MM:SS`, UTC). 이 길이까지는 사전순이 곧 시간순이다.
    `docker images` 의 `CreatedAt` 은 로컬 시간대 문자열이라 정렬 키로 쓰지 않는다."""
    if not image_ids:
        return {}
    output = _docker(["image", "inspect", "--format", "{{.Id}}\t{{.Created}}", *image_ids])
    created: dict[str, str] = {}
    for line in output.splitlines():
        if line.strip():
            image_id, timestamp = line.split("\t")
            created[image_id] = timestamp[:19]
    return created


def newest(created: dict[str, str], keep: int) -> set[str]:
    """생성 시각 내림차순 `keep` 개. 시각이 같으면 ID 로 순서를 고정한다."""
    newest_first = sorted(created, key=lambda image_id: (created[image_id], image_id), reverse=True)
    return set(newest_first[:keep])


def prune(repo: str, keep: int) -> int:
    """`repo` 의 로컬 이미지를 정리하고 실패한 삭제 수를 돌려준다."""
    images = list_repo_images(repo)
    protected = running_image_ids()
    tagged = [image_id for image_id, tags in images.items() if tags]
    kept = newest(created_at(tagged), keep) | protected

    targets: list[str] = []
    for image_id, tags in images.items():
        if image_id in kept:
            print(f"남김 {image_id} ({', '.join(tags) or _NO_TAG})")
        elif tags:
            targets.extend(f"{repo}:{tag}" for tag in tags)
        else:
            targets.append(image_id)

    failures = 0
    for target in targets:
        result = subprocess.run(["docker", "rmi", target], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"지움 {target}")
        else:
            failures += 1
            print(f"실패 {target}: {result.stderr.strip()}")
    return failures


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        # 0 이면 실행 중 이미지 하나만 남아 롤백할 곳이 사라진다.
        raise argparse.ArgumentTypeError("1 이상이어야 한다")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="정리할 이미지 저장소(태그 없이)")
    parser.add_argument("--keep", type=_positive_int, default=3, help="남길 최근 이미지 수(실행 중 이미지는 별도)")
    args = parser.parse_args()

    failures = prune(args.repo, args.keep)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as error:
        print(f"실패: {error}", file=sys.stderr)
        sys.exit(1)
