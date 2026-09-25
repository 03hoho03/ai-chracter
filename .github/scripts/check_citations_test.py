#!/usr/bin/env python3
"""check_citations.py 자체 시험. 임시 git 저장소를 만들어 케이스마다 커밋 하나를 얹고 `--base` 로 돌린다.

케이스: (이름, 파일, base 내용, head 내용, 기대 건수). 기대와 다르면 종료 코드 1.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_citations.py")

CASES = [
    # ── 잡아야 하는 것 ──
    ("F1 py 주석 + 한국어 조사", "a.py", "x = 1\n", "x = 1\n# CL-12의 규칙대로 막는다\n", 1),
    ("F2 py docstring 속 비추적 문서·절·번호", "b.py", "", 'def f():\n    """limit-goal-prompt.md §3 참고(RL-2)."""\n', 3),
    ("F3 ts // tasks 경로", "c.ts", "", "// see tasks/foo/bar\nconst a = 1;\n", 1),
    ("F4 ts 블록 주석 결정 번호", "d.ts", "", "/* D-5: 폭을 고정한다 */\nexport const w = 1;\n", 1),
    ("F5 yml 주석 비추적 문서", "e.yml", "", "on: push # backlog.md 참고\n", 1),
    ("F6 md 가 비추적 md 인용 + 결정 번호", "N.md", "", "값은 `chat-rollout-goal-prompt.md RO-12` 로 정했다.\n", 2),
    ("F7 tsx 절 번호 + 조사", "f.tsx", "", "// §5의 규칙\nexport const A = () => null;\n", 1),
    ("F8 접미 소문자·기호·숫자 접두사", "g.py", "", "# E-12a / F-7① / S11-2a\n", 3),
    ("F9 JSX 주석", "h.tsx", "", "export const A = () => (\n  <div>{/* MR-8 */}</div>\n);\n", 1),
    ("F10 템플릿 ${} 뒤 주석", "i.ts", "", "const s = `a${b}c`; // IC-11\n", 1),
    (
        "F11 JSX 뒤 새 줄만",
        "j.tsx",
        "const A = () => (\n  <div>\n    x\n  </div>\n);\nconst r = a / b; // D-1 기존\n",
        "const A = () => (\n  <div>\n    x\n  </div>\n);\nconst r = a / b; // D-1 기존\n// D-2 새 줄\n",
        1,
    ),
    ("F12 플러그인 코드 FSD", "k.ts", "", "// FSD-06 레이어 방향을 지킨다\nexport const k = 1;\n", 1),
    ("F13 플러그인 코드 TS·IMP", "l.tsx", "", "// TS-01, IMP-01 에 따라\nexport const l = 1;\n", 2),
    (
        "F14 플러그인 코드 나머지",
        "m.py",
        "",
        "# COMP-04 / FORM-02 / NAME-01 / STATE-03 / STYLE-02\n",
        5,
    ),
    ("F15 주석 속 R-1", "n.py", "", 'RULE = "R-1"  # R-1 게시 규칙\n', 1),
    ("F16 md 의 tasks 문서는 한 번만", "Q.md", "", "`tasks/foo.md` 를 보라.\n", 1),
    ("F17 추적 README 도 tasks 아래면 잡는다", "Q2.md", "", "tasks/fixtures/README.md 참고\n", 1),
    ("F18 cron 설정 주석", "ops/cron.d/job", "", "# D-5 로 새벽에 돈다\n0 3 * * * root /bin/true\n", 1),
    ("F19 logrotate 설정 주석", "ops/logrotate.d/app", "", "# backlog.md 참고\n/var/log/x { daily }\n", 1),
    ("F20 확장자 없는 README 는 문서", "mig/README", "", "backlog.md 와 D-5 를 따른다.\n", 2),
    (
        "F21 `++ ` 로 시작하는 추가 줄이 파일을 끊지 않는다",
        "S.md",
        "x\n-- a\ny\nz\nw\n",
        "x\n++ b/c\ny\nz\nw\ntasks/foo.md\n",
        1,
    ),
    ("F22 코드의 테스트 이름 속 문서", "t.test.ts", "", 'it("limit-goal-prompt.md 대로 막는다", () => {});\n', 1),
    ("F23 py 문자열 속 문서", "t_py.py", "", '@mark.parametrize("c", ["chat-rollout.md"])\ndef test_a(c): ...\n', 1),
    ("F24 주석 속 tasks 문서는 한 번만", "u.ts", "", "// tasks/foo.md 대로\nexport const u = 1;\n", 1),
    ("F25 규칙 코드 파일에서도 R-9·다른 번호는 잡는다", "apps/api/src/api/admin/prompts.py", "", "# R-9 와 CL-1\n", 2),
    (
        "F26 응답 스키마 파일이어도 목록 밖 클래스·클래스 안 주석은 잡는다",
        "apps/api/src/api/chat/prompt_builder.py",
        "",
        'class StatJudgmentResult:\n    """D-1."""\n    # D-2\n    x: int\n\n\nclass Other:\n    """D-3."""\n',
        2,
    ),
    (
        "F27 고정 줄도 내용이 바뀌면 잡는다",
        "apps/api/migrations/versions/b72c33c70240_prompt_sections_user_persona_slot.py",
        "",
        '_NOTE = "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-14)"\n',
        1,
    ),
    (
        "F28 수용 기준 번호(붙임·띄움·하이픈) + 조사",
        "v.py",
        "",
        'def f():\n    """AC3의 조건과 AC 3, AC4a."""\n# AC-3 대로\n',
        4,
    ),
    ("F29 ts 주석의 수용 기준 번호", "w.ts", "", "// (AC 3, 항상 최신)\nexport const w = 1;\n", 1),
    (
        "F30 md 안의 결정 번호·플러그인 코드·절 번호·수용 기준 번호",
        "P.md",
        "",
        "D-5 와 FSD-06 은 폐기됐다.\n값은 `DESIGN.md` §2 를 본다(MR-2a 이후).\nAC3 를 만족한다.\n",
        5,
    ),
    ("F32 경로 패턴 예외는 그 줄 내용 그대로일 때만", ".worktreeinclude", "", "# tasks/other/**\n", 1),
    ("F31 md 코드 블록 안도 줄 전체를 본다", "P2.md", "", "```sh\n# D-5 로 정했다\necho ok\n```\n", 1),
    # ── 통과해야 하는 것 ──
    ("P26 주석 처리된 경로 패턴(고정 줄)", ".worktreeinclude", "", "# 설명\n# tasks/baseline/**\n", 0),
    ("P1 py 문자열 식별자", "p1.py", "", 'RULE = "R-1"\nraise E(code="RL-3")\n', 0),
    ("P2 ts 문자열 식별자", "p2.ts", "", 'const rule = "R-8";\n', 0),
    ("P3 기술 용어", "p3.py", "", "# UTF-8 로 읽는다. SHA-256, RS-256 서명, ISO-8601\n", 0),
    ("P4 추적 문서 + 절 제목", "p4.ts", "", "// DESIGN.md 'Colors' 절, apps/api/CLAUDE.md\n", 0),
    ("P5 cite-ok", "p5.py", "", "# R-1 cite-ok: 로그에 나가는 규칙 이름\n", 0),
    (
        "P6 md 의 기술 용어·절 제목·URL·cite-ok",
        "P6.md",
        "",
        "UTF-8, SHA-256, RS-256, P-256, WCAG 1.4.11, ISO-8601.\n"
        "`DESIGN.md` 의 \"Colors\" 절, h-14·px-4.\n"
        "https://example.com/issues/D-5\n"
        "커밋 `feat: US-014` 는 D-7 로 남았다 cite-ok 인용 예시\n",
        0,
    ),
    ("P7 URL 안의 md", "p7.ts", "", "// https://github.com/x/y/blob/main/CHANGES.md\n", 0),
    ("P8 문자열 안의 //", "p8.ts", "", "const s = `// D-1`;\nconst t = 'http://a/D-2';\n", 0),
    ("P9 정규식 리터럴 안의 //", "p9.ts", "", "const re = /\\/\\/ D-1/;\n", 0),
    ("P10 삭제된 줄·기존 줄", "p10.py", "# CL-3 옛 주석\n# CL-4 남는 주석\nx = 1\n", "# CL-4 남는 주석\nx = 2\n", 0),
    ("P11 tailwind·소문자", "p11.tsx", "", "// px-4 gap-2 h-14 로 맞춘다\n", 0),
    ("P12 경로 중간 tasks/", "p12.py", "", "# api/tasks/queue.py 가 소비한다\n", 0),
    ("P13 .md 가 아닌 확장자", "p13.ts", "", "// foo.mdx 와 bar.md5\n", 0),
    ("P14 생성물은 건너뛴다", "generated.ts", "", "// D-5 CL-12\n", 0),
    ("P15 md 가 tasks 디렉터리를 일반적으로 말함", "Q3.md", "", "`tasks/` 문서를 인용하지 않는다. tasks/ 는 gitignore 대상이다.\n", 0),
    ("P16 기술 용어 추가분", "p16.py", "", "# ECMA-262, IEEE-754, GPT-4, P-256, P-384, P-521\n", 0),
    ("P17 규칙 코드 정의 파일", "apps/api/src/api/admin/prompts.py", "", "# R-1 과 R-8 을 검사한다\n", 0),
    ("P18 규칙 코드 테스트", "apps/api/tests/test_admin_prompts_api.py", "", "# R-3 위반이면 422\n", 0),
    ("P19 규칙 코드 마이그레이션", "apps/api/migrations/versions/b72c33c70240_x.py", "", "# R-2 를 적용한다\n", 0),
    ("P20 코드 문자열의 tasks 경로·추적 문서", "p20.py", "", 'Q = "tasks/queue"\nopen("README.md")\n', 0),
    (
        "P21 응답 스키마 클래스 docstring(여러 줄)",
        "apps/api/src/api/chat/prompt_builder.py",
        "",
        'class EndingJudgmentResult:\n    """techspec-backend-chat.md §3.1\n    판정(D-1).\n    """\n\n    x: int\n',
        0,
    ),
    (
        "P22 응답 스키마 클래스 docstring(다른 파일)",
        "apps/api/src/api/content/publish.py",
        "",
        'class PublishFilterResult:\n    """techspec-backend-content.md §1.3 판단용."""\n',
        0,
    ),
    (
        "P23 적용된 마이그레이션의 고정 문자열",
        "apps/api/migrations/versions/b72c33c70240_prompt_sections_user_persona_slot.py",
        "",
        '_NOTE = "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-13)"\n',
        0,
    ),
    (
        "P24 그 문자열을 단언하는 테스트 줄",
        "apps/api/tests/test_persona_prompt_slot_migration.py",
        "",
        'def t(active):\n    assert active.note == "대화 프로필 슬롯 추가 (persona-goal-prompt.md UP-13)"\n',
        0,
    ),
    (
        "P25 수용 기준 번호처럼 생긴 식별자·문자열",
        "p25.py",
        "",
        '# AC_POWER 와 ACME, AC 전원, ACK3\nK = "AC3"\nmsg = f"AC 4 {x}"\n',
        0,
    ),
]

# `--all` 은 기존 줄도 본다: base 의 j.tsx `D-1` 1건 + p10.py `CL-3`·`CL-4` 2건.
ALL_ON_BASE = 3


def git(cwd: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def write(root: str, name: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.join(root, name)), exist_ok=True)
    with open(os.path.join(root, name), "w", encoding="utf-8") as f:
        f.write(content)


def check(root: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, CHECK, *args], cwd=root, capture_output=True, text=True)


def count(stderr: str, name: str | None = None) -> int:
    """`경로:줄: 내용` 형식의 보고 줄 수. name 이 있으면 그 파일 것만 센다."""
    hits = [ln for ln in stderr.splitlines() if re.match(r"[^\s:]+:\d+: ", ln)]
    return sum(ln.startswith(f"{name}:") for ln in hits) if name else len(hits)


def main() -> int:
    root = tempfile.mkdtemp(prefix="check_citations_")
    fails = 0
    try:
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "user.email", "test@example.com")
        git(root, "config", "user.name", "test")
        for doc in ("DESIGN.md", "apps/api/CLAUDE.md", "README.md"):
            os.makedirs(os.path.join(root, os.path.dirname(doc)), exist_ok=True)
            write(root, doc, "# doc\n")
        for _, name, base, _, _ in CASES:
            if base:
                write(root, name, base)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        base = git(root, "rev-parse", "HEAD").strip()

        for label, name, _, head, want in CASES:
            git(root, "checkout", "-q", base)
            git(root, "checkout", "-q", "-B", "t")
            write(root, name, head)
            git(root, "add", "-A")
            git(root, "commit", "-qm", label)
            r = check(root, "--base", base)
            got = count(r.stderr, name)
            ok = got == want and r.returncode == (1 if want else 0)
            fails += not ok
            print(f"{'ok ' if ok else 'BAD'} {label}: want={want} got={got} rc={r.returncode}")
            if not ok:
                print(r.stdout + r.stderr)

        git(root, "checkout", "-q", base)
        r = check(root, "--all")
        got = count(r.stderr)
        ok = got == ALL_ON_BASE and r.returncode == 1
        fails += not ok
        print(f"{'ok ' if ok else 'BAD'} --all 은 기존 줄도 잡는다: want={ALL_ON_BASE} got={got} rc={r.returncode}")
        if not ok:
            print(r.stdout + r.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n{len(CASES) + 1 - fails}/{len(CASES) + 1} 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
