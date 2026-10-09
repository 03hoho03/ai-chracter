"""라우터 네임스페이스를 패치하는 테스트가 조용히 빗나가지 않게 고정한다.

라우터와 `chat/turn_prompt.py`·`chat/room_stats.py` 는 같은 함수를 각자 `from ... import 이름` 으로 가져와
부른다. 테스트가 `monkeypatch.setattr(chat_router, "이름", ...)` 로 감싸면 라우터에 남은 호출부만 바뀌고, 옮겨 간
호출부(생성 프롬프트 조립·생성 세트 고르기·상황 노트 평가)는 원래 함수를 그대로 부른다. 라우터에서 이름이 아예
사라졌다면 `AttributeError` 로 시끄럽게 깨지지만, 이름이 남아 있으면 패치가 성공하고 단언만 헛돈다.

그래서 "라우터에 남아 있으면서 호출부 일부가 옮겨 간 이름"을 지키는 목록에 두고, 테스트 파일들을 `ast` 로 훑어
그 이름을 라우터에 패치하는 곳을 찾는다. 라우터 쪽 호출부만 감싸는 것이 맞는 패치는 허용 목록에 이유와 함께 적는다.
"""

import ast
from pathlib import Path

import api.chat.router as chat_router

TESTS_DIR = Path(__file__).parent
CHAT_DIR = Path(chat_router.__file__).parent
ROUTER_MODULE = "api.chat.router"

# 라우터에 계속 import 돼 있고 라우터 안 호출부도 남아 있지만, 일부 호출부가 아래 모듈들로 옮겨 간 이름.
# 타입·모델 클래스는 넣지 않는다 — 옮긴 코드에서 주석으로만 쓰거나 생성자 호출이 라우터에만 있다. `settings` 도
# 넣지 않는다 — 테스트는 모듈 속성이 아니라 `settings` 객체의 속성을 패치하므로 대상 객체가 같아 빗나가지 않는다.
GUARDED = frozenset(
    {
        "load_room_stats",
        "format_persona",
        "preview_ending_rule_list_item",
        "get_cached_active_prompt_set",
        "set_cached_active_prompt_set",
        "load_active_prompt_set",
        "load_current_summary",
        "prompt_window",
        "evaluate_rule_list",
    }
)
MOVED_CALLER_MODULES = ("turn_prompt.py", "room_stats.py")

# `파일::함수`(클래스 안이면 `파일::클래스::함수`) → 라우터 쪽 패치가 맞는 이유.
ALLOWLIST = {
    "test_chat_model_prompt_sets.py::test_gemini_room_does_not_read_any_model_set": (
        "판정용 Gemini 세트 의존성(`_active_prompt_set_dependency`)의 조회를 센다. 생성 세트 조회는 같은 테스트가 "
        "`turn_prompt` 를 함께 감싸서 센다."
    ),
}


def _router_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "api.chat":
            aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "router")
        elif isinstance(node, ast.Import):
            aliases.update(alias.asname for alias in node.names if alias.name == ROUTER_MODULE and alias.asname)
    return aliases


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _patched_router_name(call: ast.Call, aliases: set[str]) -> str | None:
    """`setattr(<라우터>, "X", ...)`·`patch.object(<라우터>, "X")`·`setattr("api.chat.router.X", ...)`·
    `patch("api.chat.router.X")` 꼴이면 X 를 돌려준다."""
    func = call.func
    func_name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
    if func_name not in {"setattr", "delattr", "object", "patch"} or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        prefix = ROUTER_MODULE + "."
        return first.value[len(prefix) :] if first.value.startswith(prefix) else None
    target = _dotted(first)
    if (target in aliases or target == ROUTER_MODULE) and len(call.args) > 1:
        second = call.args[1]
        if isinstance(second, ast.Constant) and isinstance(second.value, str):
            return second.value
    return None


def _router_patches() -> list[tuple[str, str]]:
    """테스트 파일 전체에서 라우터 네임스페이스 패치를 `(노드 id, 이름)` 으로 모은다."""
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, path: list[str], aliases: set[str], file_name: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_path = path
            if isinstance(child, ast.ClassDef) or (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not any(not p.startswith("class:") for p in path)
            ):
                # 클래스 이름과 가장 바깥 함수 이름까지만 노드 id 에 넣는다(안쪽 헬퍼는 그 함수의 패치로 센다).
                child_path = [*path, f"class:{child.name}" if isinstance(child, ast.ClassDef) else child.name]
            if isinstance(child, ast.Call):
                name = _patched_router_name(child, aliases)
                if name is not None:
                    parts = [p.removeprefix("class:") for p in child_path]
                    found.append(("::".join([file_name, *parts]), name))
            visit(child, child_path, aliases, file_name)

    for test_file in sorted(TESTS_DIR.rglob("*.py")):
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        visit(tree, [], _router_aliases(tree), test_file.relative_to(TESTS_DIR).as_posix())
    return found


def test_no_test_patches_a_router_name_whose_callers_partly_moved_out() -> None:
    offending = sorted(
        f"{node_id} -> {name}"
        for node_id, name in _router_patches()
        if name in GUARDED and node_id not in ALLOWLIST
    )
    assert offending == [], (
        "라우터에 패치해도 옮겨 간 호출부(turn_prompt·room_stats)에는 닿지 않는 이름이다. 그 모듈도 함께 패치하거나, "
        "라우터 쪽 호출부만 바꾸는 것이 의도라면 허용 목록에 이유를 적어라: " + ", ".join(offending)
    )


def test_every_allowlisted_test_still_patches_a_guarded_router_name() -> None:
    patched = {node_id for node_id, name in _router_patches() if name in GUARDED}
    stale = sorted(set(ALLOWLIST) - patched)
    assert stale == [], f"허용 목록 항목이 가리키는 패치가 더는 없다 — 항목을 지워라: {stale}"


def test_guarded_names_are_router_attributes_still_called_from_moved_modules() -> None:
    """지키는 목록이 헛돌지 않게 한다 — 라우터에서 사라진 이름은 패치가 `AttributeError` 로 이미 깨지고, 옮겨 간
    모듈이 더는 부르지 않는 이름은 라우터 패치가 빗나갈 일이 없다. 둘 다 목록에서 빼야 할 항목이다."""
    called: set[str] = set()
    for module_file in MOVED_CALLER_MODULES:
        tree = ast.parse((CHAT_DIR / module_file).read_text(encoding="utf-8"))
        called.update(
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
    assert sorted(name for name in GUARDED if not hasattr(chat_router, name)) == []
    assert sorted(GUARDED - called) == []
