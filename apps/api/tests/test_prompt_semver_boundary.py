"""프롬프트 판 표는 어드민과 모델 정의만 안다 — 서빙 경로(채팅·LLM·소설·심사)가 판 표를 읽지 않는다는 경계.

판은 게시 세트의 부속 기록이고, 서빙이 읽는 활성 세트 조회·캐시·리플레이 기록은 판과 무관해야 서빙 프롬프트 바이트가 그대로다.
서빙 경로가 판 모델이나 판 계산 모듈을 import 하기 시작하면 이 테스트가 먼저 빨강이 된다."""

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "api"
_SEMVER_MODELS = {"PromptSetSemver", "PromptSectionSemver"}
_ALLOWED_DIRS = {_SRC / "admin", _SRC / "db" / "models"}


def _importers() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: set[str] = set()
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = {alias.name for alias in node.names}
                names |= imported & _SEMVER_MODELS
                if node.module == "api.admin.prompt_semver" or (
                    node.module == "api.admin" and "prompt_semver" in imported
                ):
                    names.add("prompt_semver")
            elif isinstance(node, ast.Import):
                names |= {"prompt_semver" for alias in node.names if alias.name == "api.admin.prompt_semver"}
            for name in names:
                found.setdefault(name, set()).add(str(path.relative_to(_SRC)))
    return found


def test_only_admin_and_model_modules_import_the_semver_tables() -> None:
    importers = _importers()
    outside = {
        name: sorted(path for path in paths if not any((_SRC / path).is_relative_to(d) for d in _ALLOWED_DIRS))
        for name, paths in importers.items()
    }
    assert {name: paths for name, paths in outside.items() if paths} == {}
    # 경계가 공허하게 통과하지 않게 — 실제로 판을 쓰는 곳이 잡힌다.
    assert "admin/prompts.py" in importers["prompt_semver"]
    assert "admin/prompt_semver.py" in importers["PromptSetSemver"]
