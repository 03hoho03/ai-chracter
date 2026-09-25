#!/usr/bin/env python3
"""코드 주석이 저장소 밖 문서나 결정 번호에 기대지 않게 막는다.

주석은 이유를 스스로 담아야 한다. `tasks/` 는 gitignore 대상이라 그 문서를 가리키는
인용은 이 머신 밖에서 끊기고, 결정 번호(`CL-12` 같은 것)는 원문 없이는 뜻이 없다.
결정의 추적은 커밋 메시지와 PR 본문이 맡는다.

잡는 것 (추가된 줄만, `--all` 이면 추적 파일 전체):
  (a) 추적되지 않는 `*.md` 이름 — 모든 파일의 줄 전체(테스트 이름·describe 문자열도 포함)
      `tasks/<무언가>` 경로 — 코드는 주석 안만, 문서는 줄 전체. 디렉터리 이름만 말하는 `tasks/` 는 인용이 아니다.
  (b) 결정 번호 패턴·수용 기준 번호(`AC3`·`AC 3`)와 `§숫자` — 코드는 주석·docstring 안만(문자열
      리터럴·식별자는 보지 않는다), 문서는 줄 전체. 추적 문서를 가리킬 때도 `§숫자` 대신 절 제목을 쓴다.
억제: 같은 줄에 `cite-ok` 를 적는다(그 줄이 왜 예외인지 옆에 한 마디 남길 것).
      줄에 주석을 달 수 없는 예외는 `SCHEMA_DOCSTRING_CLASSES`·`FROZEN_LINES` 에 등록한다.

사용:
  check_citations.py --base <ref> [--head <ref>]   # base...head 의 추가 줄
  check_citations.py --all [--head <ref>]           # 추적 파일 전체
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
import warnings

SUPPRESS = "cite-ok"

# 검사하지 않는 경로: 생성물(원본 쪽에서 이미 잡힌다), 락파일, 이 스크립트 자신.
SKIP_PATH = re.compile(
    r"(^|/)(pnpm-lock\.yaml|uv\.lock|generated\.ts|openapi\.json|routeTree\.gen\.ts)$"
    r"|^\.github/scripts/check_citations"
    r"|^tasks/"
)

# (b) 결정 번호: 대문자로 시작하는 1~5자 접두사 + `-` + 숫자(+소문자 한 자).
# 앞뒤 경계는 ASCII 로만 건다 — `\b` 는 한글도 단어 문자로 봐서 `CL-12의` 를 놓친다.
DECISION_ID = re.compile(r"(?<![A-Za-z0-9_.\-/])([A-Z][A-Z0-9]{0,4})-(\d+)[a-z]?(?![A-Za-z0-9_])")
SECTION_NO = re.compile(r"§\s?\d")
# 수용 기준 번호: `AC3`·`AC 3`. 하이픈형 `AC-3` 은 위 결정 번호 패턴이 이미 잡으므로 여기서는 뺀다.
# 경계는 결정 번호와 같다 — `AC3의` 는 잡고, `AC_POWER`·`ACME` 는 `AC` 뒤에 숫자가 오지 않아 안 잡힌다.
ACCEPTANCE_ID = re.compile(r"(?<![A-Za-z0-9_.\-/])AC ?\d+[a-z]?(?![A-Za-z0-9_])")
# 결정 번호처럼 생긴 기술 용어. 여기 없으면 그 줄에 `cite-ok`.
# 개인 FE 컨벤션 플러그인의 규칙 코드(FSD·TS·IMP·COMP·FORM·NAME·STATE·STYLE)는 일부러 넣지 않는다 —
# 그 규칙 문서도 저장소 밖에 있어서 결정 번호와 똑같이 끊긴 인용이다.
TECH_PREFIX = {"UTF", "SHA", "ISO", "RFC", "AES", "CVE", "TLS", "WCAG", "ECMA", "IEEE", "GPT"}
JWT_ALG = {"HS", "RS", "ES", "PS"}  # HS-256 등. 숫자가 256/384/512 일 때만 기술 용어로 본다.
EC_CURVE = {"256", "384", "521"}  # P-256 등 타원곡선 이름.

# 프롬프트 세트 게시 검증의 규칙 코드 `R-1`~`R-8` 은 422 응답의 `detail.rule` 로 실제로 나가는
# API 에러 코드다. 그 규칙을 정의하는 파일, 그 응답을 검사하는 테스트, 그 규칙을 처음 적용한
# 마이그레이션에서만 식별자로 보고, 다른 곳에서는 여전히 결정 번호로 잡는다.
RULE_CODE = re.compile(r"R-[1-8]")
RULE_CODE_PATHS = re.compile(
    r"^apps/api/src/api/admin/prompts\.py$"
    r"|^apps/api/tests/test_admin_prompts_api\.py$"
    r"|^apps/api/migrations/versions/b72c33c70240_[^/]*\.py$"
)

# LLM 응답 스키마로 넘기는 클래스. pydantic 이 클래스 docstring 을 JSON 스키마의 `description` 으로
# 넣고 그 스키마가 판정 요청과 함께 모델에 전송된다 — 문구를 고치면 판정 요청이 바뀌므로 이 docstring
# 줄은 보지 않는다. 바꾸려면 판정 품질을 따로 비교하면서 바꾼다.
SCHEMA_DOCSTRING_CLASSES: dict[str, set[str]] = {
    "apps/api/src/api/chat/prompt_builder.py": {
        "StatJudgmentResult",
        "EndingJudgmentResult",
        "ImageMatchJudgmentResult",
    },
    "apps/api/src/api/content/publish.py": {"PublishFilterResult"},
}
# 이미 적용된 마이그레이션이 DB 에 기록한 문자열과 그 값을 그대로 단언하는 테스트 줄. 값을 바꾸면
# 적용된 DB 와 어긋난다. 줄 내용이 정확히 같을 때만 예외다 — 내용이 바뀌면 다시 잡힌다.
FROZEN_LINES: dict[str, set[str]] = {
    "apps/api/migrations/versions/b72c33c70240_prompt_sections_user_persona_slot.py": {
        '_NOTE = "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-13)"',
    },
    "apps/api/tests/test_persona_prompt_slot_migration.py": {
        '    assert active.note == "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-13)"',
    },
}

# (a) `.md` 파일 이름(경로 포함 가능)과 `tasks/` 아래 무언가를 가리키는 경로.
MD_REF = re.compile(r"(?<![A-Za-z0-9_.\-/])((?:[A-Za-z0-9_.\-]+/)*([A-Za-z0-9_.\-]+\.md))(?![A-Za-z0-9_])")
TASKS_REF = re.compile(r"(?<![A-Za-z0-9_.\-/])tasks/(?=[A-Za-z0-9_.*\-])")
URL = re.compile(r"https?://\S+")

PY = {".py"}
C_LIKE = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
CSS = {".css"}
HASH = {".yml", ".yaml", ".sh", ".toml", ".ini", ".cfg", ".mako", ".example"}
HASH_NAMES = {"Caddyfile", "Dockerfile", ".gitignore", ".worktreeinclude", "_redirects"}
HASH_DIRS = re.compile(r"^ops/(cron|logrotate)\.d/")
SQL = {".sql"}
HTML = {".html", ".svg"}
DOC = {".md", ".txt"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def ext_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[name.rfind(".") :] if "." in name[1:] else ""


def kind_of(path: str) -> str | None:
    name, ext = path.rsplit("/", 1)[-1], ext_of(path)
    if HASH_DIRS.search(path):  # 확장자 없는 cron·logrotate 설정
        return "hash"
    if name == "README":
        return "doc"
    if ext in PY:
        return "py"
    if ext in C_LIKE:
        return "c"
    if ext in CSS:
        return "css"
    if ext in HASH or name in HASH_NAMES or name.startswith("Dockerfile"):
        return "hash"
    if ext in SQL:
        return "sql"
    if ext in HTML:
        return "html"
    if ext in DOC:
        return "doc"
    return None


# ── 주석 추출: {줄번호: [주석 텍스트, ...]} ─────────────────────────────────


def py_comments(src: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    lines = src.split("\n")
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.setdefault(tok.start[0], []).append(tok.string)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # 검사 대상의 SyntaxWarning 은 이 검사와 무관하다
            tree = ast.parse(src)
    except (SyntaxError, tokenize.TokenError):
        return {i: [line] for i, line in enumerate(lines, 1)}  # 파싱 실패 → 줄 전체를 본다
    # 문장 자리에 홀로 선 문자열 = docstring(모듈·클래스·함수 첫 줄과 속성 docstring 모두).
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                out.setdefault(ln, []).append(lines[ln - 1])
    return out


def c_comments(src: str, css: bool = False) -> dict[int, list[str]]:
    """JS/TS/CSS 주석. 문자열·템플릿 리터럴·정규식 리터럴 안의 `//` 는 주석이 아니다."""
    out: dict[int, list[str]] = {}
    i, n, line = 0, len(src), 1
    tmpl_depth: list[int] = []  # `${` 안에서 여는 중괄호 깊이
    prev = ""  # 직전의 공백 아닌 문자 (정규식 판별용)

    def emit(start_line: int, text: str) -> None:
        for k, part in enumerate(text.split("\n")):
            out.setdefault(start_line + k, []).append(part)

    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if not css and ch == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            emit(line, src[i:j])
            i = j
            continue
        if ch == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            emit(line, src[i:j])
            line += src.count("\n", i, j)
            i = j
            continue
        if ch in "'\"" or (not css and ch == "`"):
            j = i + 1
            while j < n and src[j] != ch:
                if src[j] == "\\":
                    j += 1
                elif ch == "`" and src.startswith("${", j):
                    tmpl_depth.append(0)
                    j += 2
                    break
                elif ch != "`" and src[j] == "\n":
                    break
                j += 1
            else:
                j += 1
            line += src.count("\n", i, j)
            i, prev = j, ch
            continue
        if not css and ch == "}" and tmpl_depth:
            if tmpl_depth[-1] == 0:  # `${ ... }` 끝 → 템플릿 리터럴로 복귀
                tmpl_depth.pop()
                j = i + 1
                while j < n and src[j] != "`":
                    if src[j] == "\\":
                        j += 1
                    elif src.startswith("${", j):
                        tmpl_depth.append(0)
                        j += 2
                        break
                    j += 1
                else:
                    j += 1
                line += src.count("\n", i, j)
                i, prev = j, "`"
                continue
            tmpl_depth[-1] -= 1
        if not css and ch == "{" and tmpl_depth:
            tmpl_depth[-1] += 1
        if not css and ch == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%~^"):
            j = i + 1
            in_class = False
            while j < n and src[j] != "\n":
                c = src[j]
                if c == "\\":
                    j += 1
                elif c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                j += 1
            i, prev = (j + 1 if j < n and src[j] == "/" else j), "/"  # 닫히지 않으면 줄바꿈은 남긴다
            continue
        if not ch.isspace():
            prev = ch
        i += 1
    return out


def prefix_comments(src: str, marker: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for ln, text in enumerate(src.split("\n"), 1):
        m = re.search(r"(^|\s)" + re.escape(marker), text)
        if m:
            out[ln] = [text[m.start() :]]
    return out


def html_comments(src: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for m in re.finditer(r"<!--.*?-->", src, re.S):
        start = src.count("\n", 0, m.start()) + 1
        for k, part in enumerate(m.group(0).split("\n")):
            out.setdefault(start + k, []).append(part)
    return out


def comment_map(kind: str, src: str) -> dict[int, list[str]]:
    if kind == "py":
        return py_comments(src)
    if kind == "c":
        return c_comments(src)
    if kind == "css":
        return c_comments(src, css=True)
    if kind == "hash":
        return prefix_comments(src, "#")
    if kind == "sql":
        return prefix_comments(src, "--")
    if kind == "html":
        return html_comments(src)
    return {i: [t] for i, t in enumerate(src.split("\n"), 1)}  # doc: 줄 전체


# ── 판정 ──────────────────────────────────────────────────────────────────


def url_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in URL.finditer(text)]


def inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def md_refs(text: str, tracked_md: set[str]) -> list[re.Match[str]]:
    """저장소에 없는 `.md` 를 가리키는 매치."""
    urls = url_spans(text)
    return [m for m in MD_REF.finditer(text) if not inside(m.start(), urls) and m.group(2) not in tracked_md]


def tasks_hits(text: str, tracked_md: set[str]) -> list[str]:
    """`tasks/` 경로. 이미 비추적 문서로 잡힌 매치와 겹치면 한 번만 센다."""
    taken = url_spans(text) + [m.span() for m in md_refs(text, tracked_md)]
    return ["`tasks/` 경로(gitignore 대상)" for m in TASKS_REF.finditer(text) if not inside(m.start(), taken)]


def id_hits(text: str, allow_rule_code: bool) -> list[str]:
    urls = url_spans(text)
    hits: list[str] = []
    for m in DECISION_ID.finditer(text):
        prefix, num = m.group(1), m.group(2)
        if prefix in TECH_PREFIX or (prefix in JWT_ALG and num in {"256", "384", "512"}):
            continue
        if prefix == "P" and num in EC_CURVE:
            continue
        if allow_rule_code and RULE_CODE.fullmatch(m.group(0)):
            continue
        if not inside(m.start(), urls):
            hits.append(f"결정 번호 `{m.group(0)}`")
    for m in ACCEPTANCE_ID.finditer(text):
        if not inside(m.start(), urls):
            hits.append(f"수용 기준 번호 `{m.group(0)}`")
    if SECTION_NO.search(text):
        hits.append("절 번호 `§n`(추적 문서는 절 제목으로)")
    return hits


def line_findings(line: str, comments: list[str], kind: str, path: str, tracked_md: set[str]) -> list[str]:
    """비추적 문서는 줄 전체에서(문자열 속 테스트 이름도 인용이다), 나머지는 문서면 줄 전체, 코드면 주석 안에서만 본다."""
    if SUPPRESS in line:
        return []
    hits = [f"저장소에 없는 문서 `{m.group(1)}`" for m in md_refs(line, tracked_md)]
    allow_rule_code = bool(RULE_CODE_PATHS.search(path))
    if kind == "doc":
        return hits + tasks_hits(line, tracked_md) + id_hits(line, allow_rule_code)
    for text in comments:
        hits += tasks_hits(text, tracked_md) + id_hits(text, allow_rule_code)
    return hits


def exempt_lines(path: str, src: str) -> set[int]:
    """위 두 예외 목록에 해당하는 줄 번호."""
    lines = src.split("\n")
    out = {ln for ln, text in enumerate(lines, 1) if text in FROZEN_LINES.get(path, set())}
    classes = SCHEMA_DOCSTRING_CLASSES.get(path)
    if not classes:
        return out
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in classes and node.body:
            doc = node.body[0]
            if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str):
                out.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return out


def added_lines(base: str, head: str) -> dict[str, set[int]]:
    diff = git(
        "-c", "core.quotepath=off",
        "diff", "--no-color", "--no-ext-diff", "-U0", "-M", "--diff-filter=AMR", f"{base}...{head}",
    )  # fmt: skip
    out: dict[str, set[int]] = {}
    path = None
    prev = ""
    in_header = False
    for raw in diff.split("\n"):
        # `+++ ` 는 파일 머리 안에서 `--- ` 바로 다음일 때만 파일 이름이다.
        # 추가된 줄이 `++ ` 로 시작하면 diff 에서는 `+++ ` 로 보인다.
        if raw.startswith("diff --git "):
            in_header, path = True, None
        elif in_header and raw.startswith("+++ ") and prev.startswith("--- "):
            path = raw[6:].rstrip("\t") if raw.startswith("+++ b/") else None
        elif raw.startswith("@@") and path:
            in_header = False
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            assert m
            start, count = int(m.group(1)), int(m.group(2) or "1")
            out.setdefault(path, set()).update(range(start, start + count))
        prev = raw
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--base")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()

    tracked = git("-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", args.head).splitlines()
    tracked_md = {p.rsplit("/", 1)[-1] for p in tracked if p.endswith(".md")}
    if args.all:
        targets: dict[str, set[int] | None] = {p: None for p in tracked}
    else:
        targets = dict(added_lines(args.base, args.head))

    problems = 0
    for path, lines in sorted(targets.items()):
        kind = kind_of(path)
        if kind is None or SKIP_PATH.search(path):
            continue
        try:
            src = git("show", f"{args.head}:{path}")
        except (subprocess.CalledProcessError, UnicodeDecodeError):
            continue
        comments = comment_map(kind, src) if kind != "doc" else {}
        exempt = exempt_lines(path, src)
        for ln, line in enumerate(src.split("\n"), 1):
            if (lines is not None and ln not in lines) or ln in exempt:
                continue
            for hit in line_findings(line, comments.get(ln, []), kind, path, tracked_md):
                problems += 1
                print(f"::error file={path},line={ln}::{hit} — 이유를 주석에 직접 쓰고, 결정 추적은 커밋·PR 본문에 남긴다")
                print(f"{path}:{ln}: {hit}", file=sys.stderr)
    if problems:
        print(f"\n{problems}건. 예외가 맞으면 그 줄에 `{SUPPRESS}` 를 적는다.", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
