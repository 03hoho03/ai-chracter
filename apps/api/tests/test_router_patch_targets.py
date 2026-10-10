"""라우터 네임스페이스를 패치하는 테스트가 조용히 빗나가지 않게 고정한다.

라우터와 `chat/turn_prompt.py`·`chat/room_stats.py`·`chat/turn_judgments.py`·`chat/turn_engine.py`·`chat/turn_store.py`
는 같은 함수를 각자 `from ... import 이름` 으로 가져와 부른다. 테스트가 `monkeypatch.setattr(chat_router, "이름", ...)` 로
감싸면 라우터에 남은 호출부만 바뀌고, 옮겨 간 호출부(생성 프롬프트 조립·생성 세트 고르기·상황 노트 평가·새 턴 판정·새 턴
골격·턴 쓰기와 커밋 뒤 조회, 미리보기 판정과 미리보기 턴)는 원래 함수를 그대로 부른다. 라우터에서 이름이 아예
사라졌다면 `AttributeError` 로 시끄럽게 깨지지만, 이름이 남아 있으면 패치가 성공하고 단언만 헛돈다.

그래서 "라우터에 남아 있으면서 호출부 일부가 옮겨 간 이름"을 지키는 목록에 두고, 테스트 파일들을 `ast` 로 훑어
그 이름을 라우터에 패치하는 곳을 찾는다. 라우터 쪽 호출부만 감싸는 것이 맞는 패치는 허용 목록에 이유와 함께 적는다.

훑는 범위는 좁다. 잡는 꼴은 `setattr`·`delattr`·`patch.object` 에 라우터 모듈(테스트 파일이 import 한 별칭이나
`api.chat.router`)과 문자열 리터럴 이름을 넘기는 꼴, 그리고 `setattr`·`patch` 에 `"api.chat.router.X"` 문자열을 넘기는
꼴뿐이다. 이름을 변수로 넘기는 패치(`parametrize` 뒤의 `setattr(chat_router, name, ...)` 등), `chat_router.X = ...` 직접
대입, `patch.multiple`, 모듈을 다른 변수에 담아 쓰는 꼴(`r = chat_router`, `from api import chat` 뒤의 `chat.router`)은
못 본다. 허용 목록은 테스트 함수 단위라, 허용된 함수 안에서는 지키는 이름의 라우터 패치가 더 생겨도 통과한다.
"""

import ast
from pathlib import Path

import api.chat.router as chat_router

TESTS_DIR = Path(__file__).parent
CHAT_DIR = Path(chat_router.__file__).parent
ROUTER_MODULE = "api.chat.router"

# 라우터의 속성이면서 아래 모듈들이 `이름(...)` 으로 부르는 이름. 라우터에 패치하면 그 모듈들의 호출부는 빗나간다.
# 생성자를 부르는 모델 클래스와 SQLAlchemy 함수도 같은 이유로 넣는다. 두 방향 모두 아래 테스트가 기계적으로 맞춘다.
# 부르지 않고 주석·비교에만 쓰는 공유 이름(타입, `DEFAULT_CHAT_MODEL`, `settings` 등)은 훑지 않는다.
GUARDED = frozenset(
    {
        "PromptNames",
        "GenerationPrompt",
        "select",
        "and_",
        "format_persona",
        "get_cached_active_prompt_set",
        "set_cached_active_prompt_set",
        "load_active_prompt_set",
        # 턴 판정이 부르는 것. 라우터도 계속 쓴다 — 생성 프롬프트 렌더 실패(방·미리보기)와 미리보기 저장 실패의 Bugsink
        # 승격, 엔딩 스냅숏의 규칙 조회, 스탯 정의 조회(첫 스탯 심기·콘텐츠 스냅숏).
        "capture_dependency_failure",
        "_llm_dependency_tag",
        "_ending_rule_items",
        "StatDef",
        # 턴 골격(`turn_engine`)과 턴 저장소(`turn_store`)가 부르는 것. 라우터의 다른 라우트가 쓴다(폐기 기록과 `delete` 는
        # 편집·메시지 삭제가 라우터에서 계속 쓴다).
        "TurnResult",
        "ChatMessage",
        "DiscardedResponse",
        "ChatTurn",
        "delete",
        "ChatMessageResponse",
        "ChatRoomStat",
        "CharacterImageExposure",
        "StoryEndingUnlock",
        "ChatErrorEvent",
        "run_in_threadpool",
        "resolve_media_tag_images",
        "normalize_texts",
        "normalize_texts_for_display",
        "strip_media_tags",
        "_record_story_media_unlocks",
    }
)
MOVED_CALLER_MODULES = ("turn_prompt.py", "room_stats.py", "turn_judgments.py", "turn_engine.py", "turn_store.py")
# 위 조건에 맞지만 지키지 않는 이름 → 이유.
EXCLUDED: dict[str, str] = {}

# `capture_dependency_failure` 를 라우터에 패치해 그 자리의 Bugsink 태그를 재는 테스트들의 공통 이유. 재는 흡수 자리가
# 라우터에 남아 있어(턴 생성 프롬프트 렌더·미리보기 저장), 판정·턴 골격·턴 저장소 모듈의 흡수 자리는 이 패치와 무관하다.
_ROUTER_CAPTURE_SITE = (
    "라우터에 남은 흡수 자리({site})의 Bugsink 태그를 잰다 — 판정·턴 골격·턴 저장소 모듈의 흡수 자리는 재지 않는다."
)
# 보내기 라우트 본문의 첫 문장(라우터에 남은 선행 작업)을 깨는 테스트들의 공통 이유.
_ROUTER_BODY_FIRST_READ = (
    "보내기 라우트 본문의 첫 히스토리 읽기(`select(ChatMessage)`)를 깨 첫 이벤트 전 실패의 환급을 잰다 — 그 읽기는 "
    "라우터에 남은 선행 작업이고, 턴 저장소의 응답 메시지 생성은 재지 않는다."
)

# `파일::함수`(클래스 안이면 `파일::클래스::함수`) → 라우터 쪽 패치가 맞는 이유.
ALLOWLIST = {
    "test_chat_model_prompt_sets.py::test_gemini_room_does_not_read_any_model_set": (
        "판정용 Gemini 세트 의존성(`_active_prompt_set_dependency`)의 조회를 센다. 생성 세트 조회는 같은 테스트가 "
        "`turn_prompt` 를 함께 감싸서 센다."
    ),
    "test_chat_model_billing.py::test_route_body_failure_before_the_first_event_refunds_the_premium_price": (
        _ROUTER_BODY_FIRST_READ
    ),
    "test_clover_chat_refund.py::_run_body_failure": (
        _ROUTER_BODY_FIRST_READ
        + " 같은 함수가 편집 라우트 본문의 절단 `delete(ChatMessage)` 도 깬다 — 그 절단도 라우터에 남은 선행 작업이고, "
        "턴 저장소의 재생성 옛 응답 삭제는 재지 않는다."
    ),
    "test_preview_message_api.py::test_send_preview_message_redis_save_failure_still_completes_the_turn": (
        _ROUTER_CAPTURE_SITE.format(site="미리보기 세션 저장")
    ),
    "test_preview_message_api.py::test_send_preview_message_serialization_failure_at_save_still_completes_the_turn": (
        _ROUTER_CAPTURE_SITE.format(site="미리보기 세션 저장")
    ),
    "test_prompt_render_failure_api.py::test_send_message_with_broken_section_body_ends_the_stream_with_an_error_event": (
        _ROUTER_CAPTURE_SITE.format(site="새 턴 생성 프롬프트 렌더 실패")
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
        "라우터에 패치해도 옮겨 간 호출부(turn_prompt·room_stats·turn_judgments·turn_engine·turn_store)에는 닿지 않는 이름이다. 그 모듈도 함께 패치하거나, "
        "라우터 쪽 호출부만 바꾸는 것이 의도라면 허용 목록에 이유를 적어라: " + ", ".join(offending)
    )


def test_every_allowlisted_test_still_patches_a_guarded_router_name() -> None:
    patched = {node_id for node_id, name in _router_patches() if name in GUARDED}
    stale = sorted(set(ALLOWLIST) - patched)
    assert stale == [], f"허용 목록 항목이 가리키는 패치가 더는 없다 — 항목을 지워라: {stale}"


def _names_called_from_moved_modules() -> set[str]:
    called: set[str] = set()
    for module_file in MOVED_CALLER_MODULES:
        tree = ast.parse((CHAT_DIR / module_file).read_text(encoding="utf-8"))
        called.update(
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
    return called


def test_guarded_names_are_router_attributes_still_called_from_moved_modules() -> None:
    """지키는 목록이 헛돌지 않게 한다 — 라우터에서 사라진 이름은 패치가 `AttributeError` 로 이미 깨지고, 옮겨 간
    모듈이 더는 부르지 않는 이름은 라우터 패치가 빗나갈 일이 없다. 둘 다 목록에서 빼야 할 항목이다."""
    called = _names_called_from_moved_modules()
    assert sorted(name for name in GUARDED | set(EXCLUDED) if not hasattr(chat_router, name)) == []
    assert sorted((GUARDED | set(EXCLUDED)) - called) == []


def test_every_router_attribute_called_from_moved_modules_is_guarded_or_excluded() -> None:
    """옮겨 간 모듈이 라우터와 같은 이름을 새로 부르기 시작하면 지키는 목록에 넣거나 이유와 함께 제외하게 한다."""
    shared = {name for name in _names_called_from_moved_modules() if hasattr(chat_router, name)}
    assert sorted(shared - GUARDED - set(EXCLUDED)) == []
