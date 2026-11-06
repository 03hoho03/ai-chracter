"""서비스가 엔진·측정 서버 코드와 LLM·에러 추적 의존 없이 서는지.

서비스는 측정 서버(`chat_lab`)·엔진(`api`)·저장소 스크립트(`scripts`)를 import 하지 않는다. 그것들을 끌어오면 이미지에 엔진
코드와 그 비밀 설정이 따라 들어온다. 첫 마디를 정확히 비교한다 — 앞자리로 비교하면 서비스 자신(`chat_lab_service`)이 걸린다.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from harness import SV_ROOT

FORBIDDEN_IMPORT_ROOTS = {"api", "scripts", "chat_lab"}
# 이 서비스가 쓸 일이 없는 LLM·클라우드 SDK·에러 추적 패키지, 그리고 엔진 프로젝트 자신(`apps/api` 의 이름).
FORBIDDEN_PACKAGES = {
    "anthropic",
    "openai",
    "google-genai",
    "google-generativeai",
    "google-cloud-aiplatform",
    "vertexai",
    "voyageai",
    "litellm",
    "sentry-sdk",
    "boto3",
    "botocore",
    "aioboto3",
    "api",
}
FORBIDDEN_PACKAGE_PREFIXES = ("langchain", "llama-index", "opentelemetry-instrumentation")


def _python_files(folder: str) -> list[Path]:
    root = SV_ROOT / folder
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_import_of_engine_or_measurement_code() -> None:
    src_files = _python_files("src")
    assert src_files, "서비스 소스가 없다 — 검사할 대상이 비어 있으면 통과가 아무것도 말하지 않는다"
    files = src_files + _python_files("migrations") + _python_files("scripts") + _python_files("tests")
    hits = {
        str(path.relative_to(SV_ROOT)): sorted(_import_roots(path) & FORBIDDEN_IMPORT_ROOTS)
        for path in files
        if _import_roots(path) & FORBIDDEN_IMPORT_ROOTS
    }
    assert hits == {}


def _normalized(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _requirement_name(requirement: str) -> str:
    name = requirement
    for separator in ("[", "=", "<", ">", "!", "~", ";", " "):
        name = name.split(separator)[0]
    return _normalized(name)


def _is_forbidden(name: str) -> bool:
    return name in FORBIDDEN_PACKAGES or name.startswith(FORBIDDEN_PACKAGE_PREFIXES)


def test_no_llm_or_error_tracker_dependency() -> None:
    project = tomllib.loads((SV_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = [_requirement_name(item) for item in project["project"]["dependencies"]]
    for group in project.get("dependency-groups", {}).values():
        declared += [_requirement_name(item) for item in group if isinstance(item, str)]
    lock = tomllib.loads((SV_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = [_normalized(package["name"]) for package in lock["package"]]
    assert [name for name in declared + locked if _is_forbidden(name)] == []


def test_lock_has_no_path_dependency_besides_itself() -> None:
    # 다른 저장소 폴더(예: 엔진)를 경로 의존으로 끌어오면 이미지 빌드 컨텍스트 밖을 읽게 되고 엔진 코드가 섞인다.
    lock = tomllib.loads((SV_ROOT / "uv.lock").read_text(encoding="utf-8"))
    local = {
        package["name"]: package["source"]
        for package in lock["package"]
        if not {"registry"} & set(package.get("source", {}))
    }
    assert local == {"chat-lab-service": {"editable": "."}}


def test_ci_python_matches_image_python() -> None:
    # CI 는 setup-uv 로 `uv sync` 를 돈다. 서비스 폴더에 `.python-version` 이 없으면 uv 가 러너의 기본 파이썬을 골라, 이미지의
    # 파이썬(Dockerfile 베이스)과 다른 판에서 시험하고 타입 검사 기준 판과도 어긋난다.
    pinned_file = SV_ROOT / ".python-version"
    assert pinned_file.is_file(), "서비스 폴더에 .python-version 이 없다"
    pinned = pinned_file.read_text(encoding="utf-8").strip()
    project = tomllib.loads((SV_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["mypy"]["python_version"] == pinned
    bases = re.findall(r"^FROM python:(\d+\.\d+)-", (SV_ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)
    assert bases, "Dockerfile 에서 파이썬 베이스 이미지를 찾지 못했다"
    assert set(bases) == {pinned}
