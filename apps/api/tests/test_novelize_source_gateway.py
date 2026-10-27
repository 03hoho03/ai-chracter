"""소설화 코드가 대화방 원문을 읽는 길은 원문 관문(`api/novelize/source.py`) 하나뿐이다 — 구조 검사.

사용자가 소설에서 빼기로 한 구간(exclude)이 모델에 가지 않는다는 약속은 "원문을 읽는 곳이 하나"일 때만 지킬 수 있다. 그래서
소설화 코드(`novelize/`·`novel_public/`) 전체를 AST 로 훑어, 관문 밖에서는 메시지 표·기억 표를 이름·속성·원시 SQL 로 건드리지
않고, `api.chat` 과 `api.db.models.chat` 에서는 허용 목록의 이름만 가져온다는 것을 본다. 메시지 모델 이름은 타입 주석에만 쓸 수
있다(관문이 돌려준 행을 받는 함수의 서명). 관문 안에서도 메시지 SELECT 를 만드는 함수는 하나다."""

import ast
import inspect
import re
from pathlib import Path

from api.db import models as db_models
from api.db.models import chat as chat_models

_SRC = Path(__file__).resolve().parents[1] / "src" / "api"
_GATEWAY = _SRC / "novelize" / "source.py"
_NOVEL_DIRS = (_SRC / "novelize", _SRC / "novel_public")

# 소설화 코드가 메시지·기억 표에 닿는 모듈(`api.chat` 아래 전부와, 그 밖에서 그 표를 import 하거나 원시 SQL 로 부르는 모듈)에서
# 가져와도 되는 이름. 모두 원문을 읽지 않는다 — 프롬프트 문안 렌더·이미 읽은 메시지의 서식·메시지 키 타입·원작 상태와 방 소유
# 판정, 모델 배정 표 읽기와 그 칸의 해석(배정 표 행만 읽는다)·해석 출처의 값 타입, 그리고 내 채팅 목록 항목의 타입·정렬 키·썸네일 서명이다(목록
# 행을 읽는 함수는 미리보기 원문을 읽어 관문을 지난다).
_ALLOWED_READER_IMPORTS = {
    "api.chat.prompt_builder": {
        "PromptLane",
        "PromptNames",
        "PromptRenderError",
        "PromptSetNotFoundError",
        "_turn_text",
        "load_active_prompt_set",
        "render_prompt_channel",
        "select_sections_for_render",
    },
    "api.chat.memory_window": {"MessageKey"},
    "api.chat.prompt_routing": {"RouteSource", "resolve_stage_route"},
    "api.chat.prompt_routing_cache": {"load_prompt_routes"},
    "api.chat.router": {"_ensure_content_playable", "_get_owned_room", "my_chat_room_sort_key", "sign_room_thumbnails"},
    "api.chat.schemas": {"MyChatRoomListItem"},
}
# `api.db.models.chat` 에서 가져와도 되는 이름 — 방 행·역할 값·그림 노출 기록. 메시지·기억·턴 기록 표는 원문이나 원문에서
# 나온 글을 담는다.
_ALLOWED_CHAT_MODELS = {"ChatMessageRole", "ChatRoom", "CharacterImageExposure", "StoryMediaExposure"}
# 타입 주석에만 쓸 수 있는 이름.
_ANNOTATION_ONLY = {"ChatMessage"}
_CHAT_TABLE_MODELS = {
    name: cls
    for name, cls in inspect.getmembers(chat_models, inspect.isclass)
    if cls.__module__ == chat_models.__name__ and hasattr(cls, "__tablename__")
}
_FORBIDDEN_MODELS = set(_CHAT_TABLE_MODELS) - _ALLOWED_CHAT_MODELS
_FORBIDDEN_TABLES = re.compile(
    r"\b(" + "|".join(sorted(cls.__tablename__ for name, cls in _CHAT_TABLE_MODELS.items() if name in _FORBIDDEN_MODELS)) + r")\b",
    re.IGNORECASE,
)


def _imports_message_tables(source: str) -> bool:
    """모듈이 메시지·기억 표 모델을 import 하는가(`api.db.models`·`api.db.models.chat` 에서 금지 이름)."""
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module in ("api.db.models", "api.db.models.chat")
        and any(alias.name in _FORBIDDEN_MODELS for alias in node.names)
        for node in ast.walk(ast.parse(source))
    )


# 소설화 코드 밖에서 메시지·기억 표 모델을 import 하는 모듈(점 이름). 어드민 대화 보기처럼 `api.chat` 밖에 있는 메시지 로더도
# 여기 든다. 모델 패키지 자신은 뺀다 — 거기서 가져오는 이름은 따로 본다.
_MESSAGE_READER_MODULES = {
    ".".join(("api", *path.relative_to(_SRC).with_suffix("").parts)).removesuffix(".__init__")
    for path in _SRC.rglob("*.py")
    if not any(path.is_relative_to(directory) for directory in (*_NOVEL_DIRS, _SRC / "db"))
    and _imports_message_tables(path.read_text(encoding="utf-8"))
}


def _annotation_nodes(tree: ast.AST) -> set[int]:
    """타입 주석(인자·반환·변수 주석) 안에 있는 노드의 id."""
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                roots.append(node.returns)
            arguments = node.args
            for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]:
                if arg is not None and arg.annotation is not None:
                    roots.append(arg.annotation)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
    return {id(inner) for root in roots for inner in ast.walk(root)}


def _room_reads_outside_gateway(source: str) -> list[str]:
    """관문 밖 소설화 코드가 방 원문에 닿는 자리를 `"줄: 무엇"` 으로 돌려준다."""
    tree = ast.parse(source)
    annotations = _annotation_nodes(tree)
    found: list[str] = []
    # 메시지 모델을 가리키는 이 파일 안의 이름(별칭 포함). 주석 밖에서 쓰면 원문 읽기다.
    message_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "api.chat" or alias.name.startswith(("api.chat.", "api.db.models")):
                    found.append(f"{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            module = node.module
            for alias in node.names:
                bound = alias.asname or alias.name
                if module == "api.chat" or module.startswith("api.chat.") or module in _MESSAGE_READER_MODULES:
                    if alias.name not in _ALLOWED_READER_IMPORTS.get(module, set()):
                        found.append(f"{node.lineno}: from {module} import {alias.name}")
                elif module in ("api.db.models", "api.db.models.chat"):
                    if alias.name in _ANNOTATION_ONLY:
                        message_names.add(bound)
                    elif alias.name == "chat" or alias.name in _FORBIDDEN_MODELS:
                        found.append(f"{node.lineno}: from {module} import {alias.name}")
                elif module == "api.db" and alias.name == "models":
                    pass  # 속성 검사가 `models.ChatMessage`·`models.chat.X` 를 잡는다.
        elif isinstance(node, ast.Attribute) and id(node) not in annotations:
            if node.attr in _FORBIDDEN_MODELS or node.attr in _ANNOTATION_ONLY:
                found.append(f"{node.lineno}: .{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if table := _FORBIDDEN_TABLES.search(node.value):
                found.append(f"{node.lineno}: SQL {table.group(0)}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in message_names and id(node) not in annotations:
            found.append(f"{node.lineno}: {node.id}")
    return found


def test_the_guard_sees_every_way_of_reaching_room_messages() -> None:
    """검사 자체의 신호 — 우회 꼴마다 하나씩 잡고, 허용한 import 와 타입 주석은 통과시킨다."""
    sample = """
from api.db.models.chat import ChatMessage as M
select(M).where(M.chat_room_id == room_id)
from api.db.models.chat import ChatMemoryEpisode
from api.db.models import ChatTurn
from api.db.models import chat
models.ChatMessage.content
text("SELECT content FROM chat_messages WHERE chat_room_id = :id")
text("select summary from CHAT_MEMORY_EPISODES")
from api.chat.memory_retrieval import retrieve_memories
from api.chat.prompt_builder import build_recent_turns
import api.chat.router
from api.chat import memory_window
from api.admin.chat_view import _list_messages_page
def keep(message: M, rows: list[M]) -> M: ...
from api.chat.prompt_builder import PromptNames, _turn_text
from api.chat.memory_window import MessageKey
from api.db.models.chat import ChatMessageRole, ChatRoom
text("SELECT id FROM chat_rooms WHERE id = :id")
note: list[M] = []
"""
    lines = sorted({int(line.split(":")[0]) for line in _room_reads_outside_gateway(sample)})
    assert lines == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]


def test_only_the_gateway_reads_room_messages_in_novel_code() -> None:
    """깨지는 시나리오: 새 빌더가 메시지 표를 직접 읽거나(`select(ChatMessage)`·원시 SQL), 기억 표에서 요약을 가져오거나, 채팅 쪽
    메시지 로더를 불러 원문을 받으면, 사용자가 뺀 구간이 그 길로 모델에 간다."""
    offenders = {
        str(path.relative_to(_SRC)): found
        for directory in _NOVEL_DIRS
        for path in sorted(directory.rglob("*.py"))
        if path != _GATEWAY and (found := _room_reads_outside_gateway(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}


def test_the_forbidden_lists_cover_every_message_and_memory_table() -> None:
    """금지 목록이 모델 모듈에서 만들어진다는 것의 확인 — 메시지·기억·턴 기록 표가 새로 생겨도, 그 표를 읽는 모듈이 `api.chat`
    밖에 새로 생겨도 자동으로 들어간다. 깨지는 시나리오: 목록을 손으로 적어 두었다가 새 기억 표나 어드민 쪽 메시지 로더를 빠뜨려
    그것을 부르는 빌더가 검사를 지나간다."""
    assert {"ChatMessage", "ChatRoomMemorySnapshot", "ChatMemoryEpisode", "ChatMemoryFact", "ChatTurn"} <= (
        _FORBIDDEN_MODELS | _ANNOTATION_ONLY
    )
    assert _ALLOWED_CHAT_MODELS <= set(_CHAT_TABLE_MODELS) | {"ChatMessageRole"}
    assert all(getattr(db_models, name) is cls for name, cls in _CHAT_TABLE_MODELS.items())
    assert _FORBIDDEN_TABLES.search("chat_memory_facts") and not _FORBIDDEN_TABLES.search("chat_rooms")
    assert {"api.admin.chat_view", "api.chat.room_deletion"} <= _MESSAGE_READER_MODULES
    assert "api.core.config" not in _MESSAGE_READER_MODULES


def _message_selects_by_function(source: str) -> set[str]:
    """`select(...)`·`.select_from(...)` 에 메시지 모델(`ChatMessage` 또는 그 칸)을 넘기는 호출이 있는 함수 이름들."""
    tree = ast.parse(source)
    owners: set[str] = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
            if name not in ("select", "select_from"):
                continue
            if any(isinstance(inner, ast.Name) and inner.id == "ChatMessage" for arg in call.args for inner in ast.walk(arg)):
                owners.add(function.name)
    return owners


def test_the_gateway_builds_every_message_query_in_one_function() -> None:
    """관문 안에서도 메시지 SELECT 를 만드는 함수는 하나다 — 구간 읽기·경계 후보·다음 화 시작·남은 턴 세기가 모두 그 함수의
    조건(방·키 범위·역할)을 거친다. 깨지는 시나리오: 관문 안에 새 읽기 함수가 생겨 구간 제한 없이 방 전체를 읽는다."""
    assert _message_selects_by_function(_GATEWAY.read_text(encoding="utf-8")) == {"_room_messages"}
