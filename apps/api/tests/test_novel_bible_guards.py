"""정본 기억의 import 경계 — 소설 생성 경로가 정본 기억을 모르고, 정본 기억 표는 정해진 곳만 만지며, 코어는 모델·슬롯·규칙을
import 하지 않고 주입받는다.

경계마다 신호 테스트(위반하는 합성 소스를 검사기에 넣으면 위반으로 잡힌다)와 실제 트리 테스트(위반 0)를 짝으로 둔다 — 실제
트리만 보면 검사기가 아무것도 못 잡아도 통과한다. import 는 `ast` 로 본다(함수 안 import 포함, 상대 import 는 절대 이름으로
풀어서)."""

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"

Check = Callable[[str, str], list[str]]


def _module_of(path: str) -> tuple[str, bool]:
    """`api/novelize/worker.py` → (`api.novelize.worker`, 패키지 아님)."""
    parts = path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def imported_modules(path: str, source: str) -> set[str]:
    """`path`(src 기준 경로) 파일이 import 하는 모듈 이름들. `from a import b` 는 `a` 와 `a.b` 를 둘 다 낸다 — `b` 가
    하위 모듈일 수 있다."""
    module, is_package = _module_of(path)
    package = module.split(".") if is_package else module.split(".")[:-1]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package[: len(package) - (node.level - 1)]
                base = ".".join([*base_parts, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _is_or_under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def check_g1(path: str, source: str) -> list[str]:
    """소설 생성 경로(`novelize/`)와 채팅(`chat/`)은 정본 기억 패키지를 import 하지 않는다. 워커만 예외다."""
    if not (path.startswith(("api/novelize/", "api/chat/"))) or path == "api/novelize/worker.py":
        return []
    return sorted(name for name in imported_modules(path, source) if _is_or_under(name, "api.novel_bible"))


def _is_bible_model(name: str) -> bool:
    return name == "api.db.models.novel_bible" or name.startswith("api.db.models.novel_bible_")


def check_g1b(path: str, source: str) -> list[str]:
    """정본 기억 표 모듈은 정본 기억 패키지, 모델 패키지의 `__init__`, 삭제 경로, 그리고 표 모듈끼리만 import 한다."""
    if (
        path.startswith("api/novel_bible/")
        or path in ("api/db/models/__init__.py", "api/novelize/deletion.py")
        or path.startswith("api/db/models/novel_bible")
    ):
        return []
    return sorted(name for name in imported_modules(path, source) if _is_bible_model(name))


def check_g2(path: str, source: str) -> list[str]:
    """슬롯 패키지는 다른 슬롯 패키지와 다른 슬롯의 표 모듈을 import 하지 않는다."""
    if not path.startswith("api/novel_bible/slots/") or path.count("/") < 4:
        return []
    own = path.split("/")[3]
    found: list[str] = []
    for name in imported_modules(path, source):
        if name.startswith("api.novel_bible.slots.") and name.split(".")[3] != own:
            found.append(name)
        table_module = name.removeprefix("api.db.models.novel_bible_").split(".")[0]
        if name.startswith("api.db.models.novel_bible_") and table_module != own:
            found.append(name)
    return sorted(found)


def check_g3(path: str, source: str) -> list[str]:
    """코어·슬롯·규칙은 모델 호출 계층·어댑터·등록부·바깥 입구를 import 하지 않고, 코어는 슬롯·규칙도 import 하지 않는다."""
    if not path.startswith(("api/novel_bible/core/", "api/novel_bible/slots/", "api/novel_bible/rules/")):
        return []
    banned = ["api.llm", "api.novel_bible.adapters", "api.novel_bible.registry", "api.novel_bible.entry"]
    if path.startswith("api/novel_bible/core/"):
        banned += ["api.novel_bible.slots", "api.novel_bible.rules"]
    return sorted(
        name for name in imported_modules(path, source) if any(_is_or_under(name, prefix) for prefix in banned)
    )


_DOCSTRING_ONLY = (
    "api/novel_bible/__init__.py",
    "api/novel_bible/core/__init__.py",
    "api/novel_bible/slots/__init__.py",
    "api/novel_bible/adapters/__init__.py",
)


def check_g5(path: str, source: str) -> list[str]:
    """설정이 읽는 잎 쪽 모듈은 아무것도 끌어오지 않는다 — 패키지 `__init__` 넷은 docstring 하나뿐이고 `ids.py` 는 typing
    만 import 한다."""
    tree = ast.parse(source)
    if path in _DOCSTRING_ONLY:
        body = tree.body
        only_docstring = len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
        return [] if only_docstring else [f"{path} 본문이 docstring 하나가 아니다"]
    if path == "api/novel_bible/ids.py":
        return sorted(name for name in imported_modules(path, source) if name.split(".")[0] != "typing")
    return []


def _tree_files() -> list[Path]:
    return sorted((_SRC / "api").rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(_SRC).as_posix()


@pytest.mark.parametrize("check", [check_g1, check_g1b, check_g2, check_g3, check_g5])
def test_the_source_tree_has_no_violation(check: Check) -> None:
    violations = {
        _relative(path): found
        for path in _tree_files()
        if (found := check(_relative(path), path.read_text(encoding="utf-8")))
    }
    assert violations == {}


def test_the_tree_check_sees_the_package_files_it_guards() -> None:
    # 실제 트리 테스트가 빈 목록을 훑고 통과하지 않게, 지키는 파일이 실제로 있는지 본다.
    files = {_relative(path) for path in _tree_files()}
    assert {"api/novel_bible/__init__.py", "api/novel_bible/core/__init__.py", "api/novel_bible/ids.py"} <= files
    assert "api/novelize/worker.py" in files
    assert any(path.startswith("api/novel_bible/core/") and path.endswith("pipeline.py") for path in files)


@pytest.mark.parametrize(
    ("check", "path", "source"),
    [
        (check_g1, "api/novelize/prompts.py", "from api.novel_bible.entry import confirm_chapter"),
        (check_g1, "api/chat/router.py", "def f():\n    import api.novel_bible.registry"),
        (check_g1, "api/novelize/outline.py", "from api import novel_bible"),
        (check_g1b, "api/novelize/router.py", "from api.db.models.novel_bible_facts import NovelBibleFact"),
        (check_g1b, "api/admin/novel_bible.py", "from api.db.models.novel_bible import NovelBibleCommit"),
        (check_g2, "api/novel_bible/slots/facts/slot.py", "from api.novel_bible.slots.events.schema import X"),
        (check_g2, "api/novel_bible/slots/facts/slot.py", "from ..events import schema"),
        (check_g2, "api/novel_bible/slots/knowledge/slot.py", "from api.db.models.novel_bible_facts import F"),
        (check_g3, "api/novel_bible/core/jobs.py", "from api.llm.client import LLMClient"),
        (check_g3, "api/novel_bible/core/pipeline.py", "from ..registry import REGISTRY"),
        (check_g3, "api/novel_bible/core/pipeline.py", "from api.novel_bible.rules import RULES"),
        (check_g3, "api/novel_bible/rules/blocking.py", "from api.novel_bible.adapters.table import ADAPTERS"),
        (check_g3, "api/novel_bible/slots/events/slot.py", "from api.novel_bible import entry"),
        (check_g5, "api/novel_bible/__init__.py", '"""설명."""\nfrom api.novel_bible.entry import confirm_chapter'),
        (check_g5, "api/novel_bible/core/__init__.py", '"""설명."""\nX = 1'),
        (check_g5, "api/novel_bible/ids.py", "from typing import Literal\nfrom api.db.base import Base"),
    ],
)
def test_each_guard_catches_a_synthetic_violation(check: Check, path: str, source: str) -> None:
    assert check(path, source) != []


@pytest.mark.parametrize(
    ("check", "path", "source"),
    [
        (check_g1, "api/novelize/worker.py", "from api.novel_bible.entry import BibleWorker"),
        (check_g1b, "api/novelize/deletion.py", "from api.db.models.novel_bible import NovelBibleCommit"),
        (check_g1b, "api/db/models/novel_bible_facts.py", "from api.db.models.novel_bible import NovelBibleItem"),
        (check_g2, "api/novel_bible/slots/facts/slot.py", "from api.novel_bible.slots.facts.schema import X"),
        (check_g2, "api/novel_bible/slots/facts/slot.py", "from api.db.models.novel_bible_facts import F"),
        (check_g3, "api/novel_bible/slots/facts/slot.py", "from api.novel_bible.core.types import ItemDraft"),
        (check_g3, "api/novel_bible/rules/blocking.py", "from api.novel_bible.core.positions import precedes"),
        (check_g5, "api/novel_bible/ids.py", "from typing import Literal"),
    ],
)
def test_each_guard_lets_its_allowed_imports_through(check: Check, path: str, source: str) -> None:
    assert check(path, source) == []
