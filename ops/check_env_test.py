#!/usr/bin/env python3
"""check_env.py 자체 시험. 표준 라이브러리 unittest 만 쓴다 — CI 에서 `python3 ops/check_env_test.py`.

규칙마다 걸리는 줄과 걸리지 않는 줄을 하나씩 두고, 위반 출력에 값이 새지 않는지 따로 본다.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_env

SECRET = "s3cr3tVALUE"


def rules(text: str) -> list:
    return [rule for _, rule, _ in check_env.check_text(text)[0]]


class FormatRules(unittest.TestCase):
    # (규칙, 걸려야 하는 파일 내용, 걸리면 안 되는 파일 내용)
    CASES = (
        ("crlf", "A=1\r\n", "A=1\n"),
        ("final-newline", "A=1", "A=1\n"),
        ("leading-whitespace", "  # 주석\n", "# 주석\n"),
        ("leading-whitespace", " A=1\n", "A=1\n"),
        ("export", "export A=1\n", "EXPORTER=1\n"),
        ("no-equals", "abcd\n", "A=b\n"),
        ("key-format", "a=1\n", "A=1\n"),
        ("key-format", "A =1\n", "A_B9=1\n"),
        ("key-format", "1AB=1\n", "AB1=1\n"),
        ("key-format", "키=1\n", "KEY=1\n"),
        ("key-format", "A\tB=1\n", "A_B=1\n"),
        ("empty-value", "A=\n", "A=0\n"),
        ("whitespace", "A= 1\n", "A=1\n"),
        ("whitespace", "A=1 \n", "A=1\n"),
        ("whitespace", "A=a b\n", "A=a_b\n"),
        ("whitespace", "A=a\tb\n", "A=a-b\n"),
        ("whitespace", "A=ab #c\n", "A=ab#c\n"),
        ("quote", 'A="1"\n', "A=1\n"),
        ("quote", "A=it's\n", "A=its\n"),
        ("quote", 'A=["https://a","https://b"]\n', "A=https://a,https://b\n"),
        ("dollar", "A=ab$cd\n", "A=abcd\n"),
        ("backslash", "A=a\\nb\n", "A=a/nb\n"),
        ("leading-hash", "A=#ab\n", "A=a#b\n"),
        ("duplicate-key", "A=1\nA=2\n", "A=1\nAB=2\n"),
    )

    def test_each_rule_fires_and_stays_quiet(self) -> None:
        for rule, bad, good in self.CASES:
            with self.subTest(rule=rule, bad=bad):
                self.assertIn(rule, rules(bad))
            with self.subTest(rule=rule, good=good):
                self.assertNotIn(rule, rules(good))

    def test_blank_and_comment_lines_pass(self) -> None:
        self.assertEqual(rules('# 설명 $ "따옴표" `x` \\ #\n\n# KEY=\nA=1\n'), [])

    def test_production_shapes_pass(self) -> None:
        # 운영에 실제로 있는 모양: 쉼표 구분 오리진, 비밀번호에 쓰일 법한 기호, 퍼센트 인코딩 URL.
        text = (
            "CORS_ALLOW_ORIGINS=https://ddona.site,https://admin.ddona.site\n"
            "BUGSINK_CREATE_SUPERUSER=me@x.com:p@ss!w=rd\n"
            "DATABASE_URL=postgresql+asyncpg://u:p%40w@h:5432/db\n"
            "SECRET=a+b/c==\n"
        )
        self.assertEqual(rules(text), [])

    def test_empty_value_stops_further_value_rules(self) -> None:
        self.assertEqual(rules("A=\n"), ["empty-value"])

    def test_key_format_line_reports_no_key(self) -> None:
        violations, keys = check_env.check_text("ab12=\n")
        self.assertEqual(violations, [(1, "key-format", None)])
        self.assertEqual(keys, {})

    def test_duplicate_points_at_second_line(self) -> None:
        violations, keys = check_env.check_text("A=1\nB=2\nA=3\n")
        self.assertEqual(violations, [(3, "duplicate-key", "앞선 줄 1")])
        self.assertEqual(keys, {"A": 1, "B": 2})


class NoValueLeak(unittest.TestCase):
    def test_cli_output_never_contains_values(self) -> None:
        # 키 이름도 비밀 조각일 수 있어 출력에 나가면 안 된다 — 모든 키에 표식(LEAKKEY)을 넣어 둔다.
        bad_lines = [
            f'LEAKKEY_Q="{SECRET}"',
            f"LEAKKEY_D={SECRET}$x",
            f"LEAKKEY_I={SECRET} #c",
            f"LEAKKEY_E= {SECRET}",
            f"LEAKKEY_S={SECRET} {SECRET}",
            f"LEAKKEY_DUP={SECRET}",
            f"LEAKKEY_DUP={SECRET}",
            f"{SECRET[:4]}=",  # 줄바꿈으로 잘린 비밀값 조각이 키 자리에 왔고 키 모양이 아닌 경우
            "QZ7=",  # 같은 조각이 키 모양인 경우(openssl rand -base64 50 의 둘째 줄 꼴) — empty-value 로 잡힌다
            f"{SECRET}",
            f"export LEAKKEY_X={SECRET}",
            f"lower={SECRET}",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("\n".join(bad_lines) + "\nTAIL=1\r", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, check_env.__file__, "--format", str(path)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(proc.returncode, 1)
        out = proc.stdout + proc.stderr
        for text in (SECRET[:4], "QZ7", "LEAKKEY", "lower"):
            self.assertNotIn(text, out)
        # 위반을 실제로 잡았는지(아무것도 안 찍어서 통과하는 것이 아닌지)도 본다.
        for rule in ("quote", "dollar", "whitespace", "key-format", "empty-value", "no-equals", "export", "crlf"):
            self.assertIn(rule, out)
        self.assertIn(":7: duplicate-key 앞선 줄 6 ", out)
        self.assertIn(":9: empty-value — ", out)

    def test_clean_file_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("A=1\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_env.main(["--format", str(path)]), 0)

    def test_missing_file_is_input_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_env.main(["--format", "/nonexistent/.env"]), 2)

    def test_non_utf8_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_bytes(b"A=\xff\n")
            violations, _ = check_env.check_file(path)
        self.assertEqual(violations, [(0, "encoding", None)])


SETTINGS_SRC = textwrap.dedent(
    """
    from typing import Annotated, ClassVar, Literal, Optional
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Other(BaseSettings):
        not_me: str = ""

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", extra="ignore")

        plain: str = "x"
        no_default: int
        secret: str = Field(default="", repr=False)
        aliased: str = Field(default="", alias="Custom_Name")
        validated: str = Field(default="", validation_alias="OTHER_NAME")
        optional_new: str | None = None
        optional_old: Optional[int] = None
        literal: Literal["a", "b"] = "a"
        listed: list[str] = ["a"]
        annotated: Annotated[int, Field(ge=1)] = 1
        counter: ClassVar[int] = 0
        _private: str = ""

        def method(self) -> None:
            local_var: int = 1
    """
)


class SettingsAst(unittest.TestCase):
    def test_collects_every_field_shape(self) -> None:
        self.assertEqual(
            check_env.settings_env_names(SETTINGS_SRC),
            {
                "PLAIN",
                "NO_DEFAULT",
                "SECRET",
                "CUSTOM_NAME",
                "OTHER_NAME",
                "OPTIONAL_NEW",
                "OPTIONAL_OLD",
                "LITERAL",
                "LISTED",
                "ANNOTATED",
            },
        )

    def test_non_string_alias_fails_loudly(self) -> None:
        src = SETTINGS_SRC.replace('validation_alias="OTHER_NAME"', 'validation_alias=AliasChoices("A", "B")')
        with self.assertRaises(check_env.InputError):
            check_env.settings_env_names(src)

    def test_env_prefix_fails_loudly(self) -> None:
        src = SETTINGS_SRC.replace('env_file=".env",', 'env_file=".env", env_prefix="APP_",')
        with self.assertRaises(check_env.InputError):
            check_env.settings_env_names(src)

    def test_missing_class_fails(self) -> None:
        with self.assertRaises(check_env.InputError):
            check_env.settings_env_names("x = 1\n")

    def test_real_config_parses(self) -> None:
        names = check_env.settings_env_names(
            (check_env.repo_root() / "apps/api/src/api/core/config.py").read_text(encoding="utf-8")
        )
        for key in ("DATABASE_URL", "CORS_ALLOW_ORIGINS", "WITHDRAWN_EMAIL_HMAC_KEY", "SENTRY_ENVIRONMENT"):
            self.assertIn(key, names)
        self.assertNotIn("MODEL_CONFIG", names)


class Examples(unittest.TestCase):
    def make_root(self, tmp: str, api_example: str, web_example: str = "", admin_example: str = "") -> Path:
        root = Path(tmp)
        (root / "apps/api/src/api/core").mkdir(parents=True)
        (root / "apps/api/src/api/core/config.py").write_text(
            "class Settings(BaseSettings):\n    database_url: str = ''\n    gemini_seed: int | None = None\n",
            encoding="utf-8",
        )
        for app, text in (("web", web_example), ("admin", admin_example)):
            (root / f"apps/{app}/src").mkdir(parents=True)
            (root / f"apps/{app}/src/client.ts").write_text(
                "const a = import.meta.env.VITE_API_BASE_URL;\nconst m = import.meta.env.MODE;\n",
                encoding="utf-8",
            )
            (root / f"apps/{app}/.env.example").write_text(text, encoding="utf-8")
        (root / "apps/api/.env.example").write_text(api_example, encoding="utf-8")
        return root

    TRACKED = tuple(check_env.EXAMPLE_SOURCES)
    RUNTIME = "".join(f"# {k}=x\n" for k in check_env.API_RUNTIME_KEYS)
    WEB_OK = "# VITE_API_BASE_URL=http://localhost:8000\n"

    def run_examples(self, api: str, web: str = WEB_OK) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp, api, web, self.WEB_OK)
            return check_env.check_examples(root, list(self.TRACKED))

    def test_active_and_commented_keys_both_count(self) -> None:
        api = "DATABASE_URL=postgresql://x\n# 설명\n# GEMINI_SEED=42\n" + self.RUNTIME
        self.assertEqual(self.run_examples(api), [])

    def test_missing_settings_key(self) -> None:
        out = self.run_examples("DATABASE_URL=x\n" + self.RUNTIME)
        self.assertEqual(len(out), 1)
        self.assertIn("example-missing-key GEMINI_SEED", out[0])

    def test_missing_runtime_key(self) -> None:
        api = "DATABASE_URL=x\n# GEMINI_SEED=42\n" + self.RUNTIME.replace("# WEB_CONCURRENCY=x\n", "")
        out = self.run_examples(api)
        self.assertEqual(len(out), 1)
        self.assertIn("example-missing-key WEB_CONCURRENCY", out[0])

    def test_unknown_key_both_forms(self) -> None:
        api = "DATABASE_URL=x\n# GEMINI_SEED=42\nCLOUDFLARE_API_TOKEN=x\n# OLD_KEY=1\n" + self.RUNTIME
        out = self.run_examples(api)
        self.assertEqual(len(out), 2)
        self.assertTrue(any("example-unknown-key CLOUDFLARE_API_TOKEN" in line for line in out))
        self.assertTrue(any("example-unknown-key OLD_KEY" in line for line in out))

    def test_duplicate_across_active_and_comment(self) -> None:
        api = "DATABASE_URL=x\n# DATABASE_URL=y\n# GEMINI_SEED=42\n" + self.RUNTIME
        out = self.run_examples(api)
        self.assertEqual(len(out), 1)
        self.assertIn("example-duplicate-key DATABASE_URL", out[0])

    def test_vite_keys_from_source(self) -> None:
        out = self.run_examples("DATABASE_URL=x\n# GEMINI_SEED=42\n" + self.RUNTIME, web="")
        self.assertEqual(len(out), 1)
        self.assertIn("apps/web/.env.example", out[0])
        self.assertIn("example-missing-key VITE_API_BASE_URL", out[0])

    def test_examples_use_format_rules(self) -> None:
        api = "DATABASE_URL=x\n# GEMINI_SEED=42\nAWS_ACCESS_KEY_ID=a b\n" + self.RUNTIME.replace(
            "# AWS_ACCESS_KEY_ID=x\n", ""
        )
        out = self.run_examples(api)
        self.assertEqual(len(out), 1)
        self.assertIn("apps/api/.env.example:3: whitespace — ", out[0])

    def test_unregistered_example_is_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp, "")
            with self.assertRaises(check_env.InputError):
                check_env.check_examples(root, [*self.TRACKED, "apps/new/.env.example"])


if __name__ == "__main__":
    unittest.main()
