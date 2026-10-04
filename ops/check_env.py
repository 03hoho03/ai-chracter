#!/usr/bin/env python3
"""env 파일이 모든 읽는 쪽에서 같은 값으로 읽히는 표기만 쓰는지 검사한다.

운영 `/opt/ddona/.env` 는 compose `env_file`(앱 컨테이너), compose `--env-file`(compose 파일 보간),
`docker run --env-file`, 크론 스크립트의 `grep | cut` 이 각자 읽고, 로컬 `.env` 는 pydantic 이 쓰는
python-dotenv 와 `uv run --env-file` 이 읽는다. 파서마다 따옴표·`$`·백슬래시·공백·중복 키·`export` 를 다르게
다뤄서, 그런 표기가 하나라도 있으면 앱과 크론이 서로 다른 값을 보면서 아무도 실패하지 않는다. 그래서 여섯
파서가 모두 같은 값을 주는 좁은 표기 하나만 허용하고, 운영·로컬·example 에 같은 규칙을 건다.

형식 위반 출력은 경로·줄 번호·규칙 이름(과 고정 설명 문구)뿐이다 — 값도 키 이름도 찍지 않는다. 키 자리의
글자는 줄바꿈으로 잘린 비밀값 조각일 수 있고, 그 조각이 키 모양이면(`openssl rand -base64 50` 의 둘째 줄
`XYZ=` 꼴) 키 형식 검사를 통과해 `empty-value` 로 잡히기 때문이다. 중복 키도 키 이름 대신 앞선 줄 번호를 찍는다.
키 이름을 찍는 것은 `--examples` 의 키 일치 결과뿐이다 — 코드가 읽는 키 이름이라 비밀이 아니다.

표준 라이브러리만 쓴다 — 운영 VM 호스트의 python3(배포 스크립트), CI, 로컬 어디서나 설치 없이 돈다.
python 3.9 에서도 돈다(macOS 기본 python3).

사용:
  check_env.py --format FILE...   # 이 파일들의 형식만 검사
  check_env.py --dev              # 로컬 개발 env 파일 중 있는 것만 검사
  check_env.py --examples         # 추적되는 .env.example 형식 + 코드가 읽는 키와 양방향 일치
종료 코드: 0 = 통과, 1 = 위반, 2 = 사용법·입력 오류.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


def repo_root() -> Path:
    # 함수로 둔다 — `python3 - --format FILE < check_env.py` 처럼 stdin 으로 넘기면 `__file__` 이 없고,
    # 형식 검사에는 저장소 위치가 필요 없다.
    return Path(__file__).resolve().parent.parent


KEY = re.compile(r"[A-Z][A-Z0-9_]*")
# `.env.example` 에서 선택 키를 적는 주석 줄: `# KEY=기본값`.
COMMENTED_KEY = re.compile(r"#\s?([A-Z][A-Z0-9_]*)=")

# 규칙 이름 → 설명. 이름은 출력에 그대로 나가는 식별자다.
RULES: dict[str, str] = {
    "encoding": "UTF-8 로 읽을 수 없다",
    "crlf": "줄 끝에 CR(\\r)이 있다 — grep|cut 은 CR 을 값에 붙여 읽는다",
    "final-newline": "파일이 개행으로 끝나지 않는다",
    "leading-whitespace": "줄이 공백으로 시작한다(빈 줄은 완전히 비워 두고, 주석은 맨 앞에 #)",
    "export": "`export ` 로 시작한다 — docker run --env-file 은 파일 전체를 거부하고 grep|cut 은 키를 못 찾는다",
    "no-equals": "빈 줄·주석·KEY=value 어느 것도 아니다",
    "key-format": "키는 대문자로 시작하는 [A-Z0-9_] 이고 = 앞뒤에 공백이 없어야 한다",
    "empty-value": "값이 비어 있다 — 값이 없으면 줄을 주석으로 바꾼다",
    "whitespace": (
        "값에 공백·탭이 있다 — 앞뒤 공백은 compose·python-dotenv 만 지우고, 공백 뒤 # 는 거기서 잘리며,"
        " uv run --env-file 은 이 줄부터 파일 끝까지 버린다"
    ),
    "quote": "값에 따옴표가 있다 — compose·python-dotenv 는 감싼 따옴표를 벗기고 uv 는 안쪽 따옴표까지 벗기거나 줄을 버린다",
    "dollar": "값에 $ 가 있다 — compose·uv 는 변수로 치환하고 나머지는 글자 그대로 읽는다",
    "backslash": "값에 \\ 가 있다 — uv run --env-file 은 이스케이프로 읽는다",
    "leading-hash": "값이 # 로 시작한다 — uv run --env-file 은 빈 값으로 읽는다",
    "duplicate-key": "같은 키가 앞에서 이미 나왔다 — compose 는 뒤 값, backup.sh 는 앞 값, 다른 크론은 두 값을 이어 붙인다",
    # `--examples` 에서만 쓰는 규칙.
    "example-missing-key": "코드가 읽는 키인데 .env.example 에 활성 줄도 `# KEY=` 주석 줄도 없다",
    "example-unknown-key": ".env.example 에 있는데 코드가 읽지 않는 키다",
    "example-duplicate-key": ".env.example 에 같은 키가 활성 줄·주석 줄로 두 번 이상 있다",
}

# Settings 필드가 아닌데 라이브러리가 프로세스 env 에서 직접 읽는 키 — `apps/api/.env.example` 에 있어야 한다.
# Settings 필드는 config.py 에서 읽으므로 여기 적지 않는다.
API_RUNTIME_KEYS: dict[str, str] = {
    # boto3 가 S3(R2·moto) 클라이언트 자격증명으로 읽는다. 로컬은 moto 라 더미값이면 되지만 없으면
    # 주소 서명이 NoCredentialsError 로 실패한다.
    "AWS_ACCESS_KEY_ID": "boto3",
    "AWS_SECRET_ACCESS_KEY": "boto3",
    # uvicorn 이 직접 읽는다. Dockerfile CMD 에 --workers·--forwarded-allow-ips 가 없어 운영은 이 둘로 정한다.
    "FORWARDED_ALLOW_IPS": "uvicorn",
    "WEB_CONCURRENCY": "uvicorn",
}

# 추적되는 `.env.example` → 그 앱이 읽는 키를 내는 함수 이름. 여기 없는 example 이 생기면 실패한다.
EXAMPLE_SOURCES: dict[str, str] = {
    "apps/api/.env.example": "api",
    "apps/web/.env.example": "web",
    "apps/admin/.env.example": "admin",
}

# 로컬 개발 env 파일. 없는 것은 건너뛴다.
DEV_FILES = ("apps/api/.env", "apps/web/.env.local", "apps/admin/.env.local")

VITE_KEY = re.compile(r"import\.meta\.env\.(VITE_[A-Z0-9_]+)")

# (줄 번호, 규칙 이름, 출력해도 되는 덧붙임). 덧붙임은 형식 위반에서는 앞선 줄 번호(중복 키)뿐이고, 키 일치
# 검사에서는 코드 키 이름이다. 실행 시 평가되는 별칭이라 python 3.9 에서도 도는 Optional 을 쓴다.
Violation = tuple[int, str, Optional[str]]


class InputError(Exception):
    """검사 대상이 아니라 검사기 입력(경로·소스 구조)이 잘못된 경우."""


# ── 형식 ──────────────────────────────────────────────────────────────────


def check_text(text: str) -> tuple[list[Violation], dict[str, int]]:
    """위반 목록과 활성 키 → 첫 줄 번호를 돌려준다. 값은 어디에도 담지 않는다."""
    out: list[Violation] = []
    keys: dict[str, int] = {}
    if text and not text.endswith("\n"):
        out.append((text.count("\n") + 1, "final-newline", None))
    for no, line in enumerate(text.split("\n"), 1):
        if "\r" in line:
            out.append((no, "crlf", None))
            line = line.replace("\r", "")
        if line == "":
            continue
        if line[0] in " \t":
            out.append((no, "leading-whitespace", None))
            continue
        if line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            out.append((no, "export", None))
            continue
        if "=" not in line:
            out.append((no, "no-equals", None))
            continue
        key, value = line.split("=", 1)
        if not KEY.fullmatch(key):
            out.append((no, "key-format", None))
            continue
        if key in keys:
            out.append((no, "duplicate-key", f"앞선 줄 {keys[key]}"))
        else:
            keys[key] = no
        if value == "":
            out.append((no, "empty-value", None))
            continue
        if re.search(r"\s", value):
            out.append((no, "whitespace", None))
        if '"' in value or "'" in value:
            out.append((no, "quote", None))
        if "$" in value:
            out.append((no, "dollar", None))
        if "\\" in value:
            out.append((no, "backslash", None))
        if value.startswith("#"):
            out.append((no, "leading-hash", None))
    return out, keys


def read_text(path: Path) -> tuple[str | None, list[Violation]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"{path}: 읽을 수 없다({exc.strerror})") from None
    try:
        return raw.decode("utf-8"), []
    except UnicodeDecodeError:
        return None, [(0, "encoding", None)]


def check_file(path: Path) -> tuple[list[Violation], dict[str, int]]:
    text, bad = read_text(path)
    if text is None:
        return bad, {}
    return check_text(text)


def format_violation(label: str, v: Violation) -> str:
    no, rule, extra = v
    where = f"{label}:{no}" if no else label
    more = f" {extra}" if extra else ""
    return f"{where}: {rule}{more} — {RULES[rule]}"


# ── 코드가 읽는 키 ──────────────────────────────────────────────────────────


def settings_env_names(source: str, class_name: str = "Settings") -> set[str]:
    """config.py 를 import 하지 않고 AST 로 Settings 필드의 env 이름을 뽑는다.

    import 하면 pydantic 등 의존성이 있어야 해서 CI 의 아무 잡에서나 돌릴 수 없다.
    env 이름은 필드명 대문자이고, `Field(alias=...)`·`Field(validation_alias=...)` 가 문자열이면 그 값의
    대문자다(pydantic-settings 기본값 case_sensitive=False). 이 함수가 해석하지 못하는 형태
    (문자열이 아닌 alias, env_prefix)를 만나면 키를 놓치지 않도록 실패한다.
    """
    tree = ast.parse(source)
    cls = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name),
        None,
    )
    if cls is None:
        raise InputError(f"클래스 {class_name} 를 찾지 못했다")
    names: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "model_config" for t in node.targets
        ):
            _reject_env_prefix(node.value)
            continue
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        name = node.target.id
        if name == "model_config":
            if node.value is not None:
                _reject_env_prefix(node.value)
            continue
        if name.startswith("_") or "ClassVar" in ast.dump(node.annotation):
            continue
        env = name
        if isinstance(node.value, ast.Call):
            for kw in node.value.keywords:
                if kw.arg in ("alias", "validation_alias"):
                    if not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                        raise InputError(f"{name}: 문자열이 아닌 {kw.arg} 는 해석하지 못한다")
                    env = kw.value.value
        names.add(env.upper())
    return names


def _reject_env_prefix(value: ast.expr) -> None:
    if isinstance(value, ast.Call) and any(kw.arg == "env_prefix" for kw in value.keywords):
        raise InputError("env_prefix 는 해석하지 못한다 — 검사기에 접두사 처리를 더한다")


def vite_env_names(src_dir: Path) -> set[str]:
    names: set[str] = set()
    for path in sorted(src_dir.rglob("*")):
        if path.suffix in (".ts", ".tsx") and path.is_file():
            names.update(VITE_KEY.findall(path.read_text(encoding="utf-8")))
    return names


def code_keys(app: str, root: Path) -> set[str]:
    if app == "api":
        source = (root / "apps/api/src/api/core/config.py").read_text(encoding="utf-8")
        return settings_env_names(source) | set(API_RUNTIME_KEYS)
    return vite_env_names(root / "apps" / app / "src")


def example_keys(text: str) -> tuple[dict[str, list[int]], list[Violation]]:
    """활성 줄과 `# KEY=` 주석 줄의 키 → 줄 번호들."""
    seen: dict[str, list[int]] = {}
    for no, line in enumerate(text.split("\n"), 1):
        m = COMMENTED_KEY.match(line)
        key = m.group(1) if m else None
        if key is None and line and not line.startswith("#") and "=" in line:
            candidate = line.split("=", 1)[0]
            key = candidate if KEY.fullmatch(candidate) else None
        if key is not None:
            seen.setdefault(key, []).append(no)
    dup: list[Violation] = [(nos[1], "example-duplicate-key", k) for k, nos in seen.items() if len(nos) > 1]
    return seen, dup


def check_examples(root: Path, tracked: list[str]) -> list[str]:
    lines: list[str] = []
    for rel in tracked:
        if rel not in EXAMPLE_SOURCES:
            raise InputError(f"{rel}: 키 출처가 등록되지 않은 .env.example 이다 — EXAMPLE_SOURCES 에 더한다")
    for rel, app in EXAMPLE_SOURCES.items():
        if rel not in tracked:
            raise InputError(f"{rel}: 추적되지 않는다")
        path = root / rel
        violations, _ = check_file(path)
        text, _ = read_text(path)
        if text is not None:
            seen, dup = example_keys(text)
            violations += dup
            expected = code_keys(app, root)
            violations += [(0, "example-missing-key", k) for k in sorted(expected - set(seen))]
            violations += [(seen[k][0], "example-unknown-key", k) for k in sorted(set(seen) - expected)]
        lines += [format_violation(rel, v) for v in sorted(violations, key=lambda v: (v[0], v[1]))]
    return lines


def tracked_examples(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", "*.env.example", ".env.example"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sorted(set(out.split()))


# ── 진입점 ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", metavar="FILE")
    parser.add_argument("--format", action="store_true", help="FILE 들의 형식만 검사")
    parser.add_argument("--dev", action="store_true", help="로컬 개발 env 파일 중 있는 것을 검사")
    parser.add_argument("--examples", action="store_true", help=".env.example 형식 + 키 일치")
    args = parser.parse_args(argv)
    if not (args.format or args.dev or args.examples):
        parser.error("--format·--dev·--examples 중 하나 이상이 필요하다")
    if bool(args.files) != bool(args.format):
        parser.error("FILE 은 --format 과 함께만, --format 은 FILE 과 함께만 쓴다")

    report: list[str] = []
    checked = 0
    try:
        targets: list[tuple[Path, str]] = [(Path(p), p) for p in args.files]
        if args.dev:
            root = repo_root()
            targets += [(root / rel, rel) for rel in DEV_FILES if (root / rel).is_file()]
        for path, label in targets:
            violations, _ = check_file(path)
            report += [format_violation(label, v) for v in violations]
            checked += 1
        if args.examples:
            examples = tracked_examples(repo_root())
            report += check_examples(repo_root(), examples)
            checked += len(examples)
    except InputError as exc:
        print(f"check_env: {exc}", file=sys.stderr)
        return 2

    for line in report:
        print(line)
    if report:
        print(f"check_env: 위반 {len(report)}건 — 값은 출력하지 않는다. 규칙은 DEPLOY.md·DEV.md 의 'env 파일 형식' 절")
        return 1
    print(f"check_env: 파일 {checked}개 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
