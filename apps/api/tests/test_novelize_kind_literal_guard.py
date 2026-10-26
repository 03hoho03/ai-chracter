"""소설화 모듈에서 작업 종류 문자열로 갈라 읽는 곳은 갈래 표(`job_variants.py`)와 실행 모듈(`runner.py`, 갈래별 핸들러)뿐이다.

작업 종류(`kind`)만으로는 실행 경로가 갈리지 않는다 — 장 생성은 혼자 도는 생성과 연쇄 자식으로, 다시 만들기는 옛 흐름 묶음과
구성 흐름 화로, AI 수정은 문단 수정과 여러 문단 수정으로 다시 나뉜다. 다른 모듈이 `job.kind == "..."` 처럼 종류 문자열을 직접
비교하면 갈래가 더해지거나 사실이 바뀔 때 그 자리가 따로 남아 어긋난다. 그래서 조회·응답·과금 자리는 갈래 판정(`variant_of`)과
갈래 사실(`VARIANT_FACTS`·`kinds_where`)로 읽고, 종류 문자열 상수는 다음 문맥에서만 쓴다.

- 작업 행 만들기(`NovelJob(kind=...)`) — 새 행의 종류를 적는 값이지 분기가 아니다.
- 가격 함수의 첫 인자(`job_price("...")`) — 화면에 내려 주는 견적이 차감과 같은 함수에서 나오게 하는 값이다.
- 개정 행 만들기의 출처(`build_revision(source=...)`) — 개정 출처 "ai_edit" 는 작업 종류와 값이 같을 뿐 다른 목록이다.
- 과금 모듈의 가격 함수 본문(`job_price`·`_checked_price`) — 가격 흐름은 이 정리에서 손대지 않는다.
- 과금 함수(`create_charged_job`)에서 다시 만들기만 금액을 사용자 잠금 뒤에 계산하는 두 비교 — 가격 흐름 안이라 그대로 둔다.

작업 표 모델 모듈(`db/models/novel.py`)은 소설화 모듈 밖이라 검사하지 않는다."""

import ast
from pathlib import Path
from typing import get_args

from api.db.models.novel import NovelJobKind

_NOVELIZE = Path(__file__).resolve().parents[1] / "src" / "api" / "novelize"
_EXEMPT_MODULES = {"job_variants.py", "runner.py"}
_KINDS = frozenset(get_args(NovelJobKind))
_PRICE_FUNCTIONS = {("billing.py", "job_price"), ("billing.py", "_checked_price")}


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return None


def _allowed(node: ast.Constant, module: str, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    if isinstance(parent, ast.keyword) and isinstance(call := parents.get(parent), ast.Call):
        if parent.arg == "kind" and _callee(call) == "NovelJob":
            return True
        if parent.arg == "source" and _callee(call) == "build_revision":
            return True
    if isinstance(parent, ast.Call) and _callee(parent) == "job_price" and parent.args and parent.args[0] is node:
        return True
    function = _enclosing_function(node, parents)
    if (module, function) in _PRICE_FUNCTIONS:
        return True
    return (
        module == "billing.py"
        and function == "create_charged_job"
        and node.value == "chapter_regenerate"
        and isinstance(parent, ast.Compare)
        and isinstance(parent.left, ast.Attribute)
        and parent.left.attr == "kind"
        and len(parent.ops) == 1
        and isinstance(parent.ops[0], (ast.Eq, ast.NotEq))
        and parent.comparators[0] is node
    )


def _kind_literals(source: str, module: str) -> list[str]:
    """허용 문맥 밖에서 작업 종류와 같은 문자열 상수를 쓴 자리("줄: 값")."""
    tree = ast.parse(source)
    parents = _parents(tree)
    return [
        f"{node.lineno}: {node.value}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in _KINDS
        and not _allowed(node, module, parents)
    ]


def test_the_guard_sees_every_way_of_branching_on_a_job_kind() -> None:
    """검사 자체의 신호 — 비교·포함·모듈 상수·다른 키워드·match 패턴·가격 함수 둘째 인자를 잡고, 허용 문맥은 통과시킨다."""
    sample = """
job.kind == "ai_edit"
kind in ("ai_edit",)
_EDIT_KINDS = ("ai_edit", "chapter_generate")
NovelJob(model="ai_edit")
other(kind="chain_generate")
job_price(model, "chapter_regenerate")
match kind:
    case "outline_generate":
        pass
NovelJob(kind="ai_edit")
models.NovelJob(kind="chapter_generate")
build_revision(source="ai_edit")
job_price("ai_edit", model)
billing.job_price("chapter_regenerate")
"ai_edit_preview"
"""
    lines = sorted(int(found.split(":")[0]) for found in _kind_literals(sample, "router.py"))
    assert lines == [2, 3, 4, 4, 5, 6, 7, 9]


def test_the_guard_allows_only_the_price_flow_inside_billing() -> None:
    """과금 모듈의 가격 함수 본문과, 과금 함수의 다시 만들기 비교 두 꼴(같다·다르다)만 통과한다. 같은 과금 함수 안이라도 다른
    종류와의 비교, 같은 비교라도 다른 함수나 다른 모듈은 잡는다."""
    sample = """
def job_price(kind):
    if kind == "ai_edit":
        return 1
def _checked_price(job):
    if job.kind == "chain_generate":
        return 2
async def create_charged_job(job):
    if job.kind != "chapter_regenerate":
        pass
    if job.kind == "chapter_regenerate":
        pass
    if job.kind == "chapter_generate":
        pass
    if job.kind in ("chapter_regenerate",):
        pass
def elsewhere(job):
    return job.kind == "chapter_regenerate"
"""
    in_billing = sorted(int(found.split(":")[0]) for found in _kind_literals(sample, "billing.py"))
    assert in_billing == [13, 15, 18]
    in_router = sorted(int(found.split(":")[0]) for found in _kind_literals(sample, "router.py"))
    assert in_router == [3, 6, 9, 11, 13, 15, 18]


def test_novelize_modules_branch_on_job_kinds_only_through_the_variant_table() -> None:
    """깨지는 시나리오: 조회·응답·과금 자리가 종류 문자열을 직접 비교해, 갈래를 더하거나 갈래 사실을 고칠 때 그 자리만 옛 뜻으로
    남는다(가령 AI 수정 갈래 하나에만 걸려야 할 조건이 종류 전체에 걸린다)."""
    offenders = {
        str(path.relative_to(_NOVELIZE)): found
        for path in sorted(_NOVELIZE.rglob("*.py"))
        if path.name not in _EXEMPT_MODULES and (found := _kind_literals(path.read_text(encoding="utf-8"), path.name))
    }

    assert offenders == {}
