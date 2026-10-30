"""측정 서버 응답의 데이터 모양. 측정 서버(FastAPI)가 이 모델을 응답 모델로 그대로 쓰고, 웹은 그 openapi 로 타입을 만든다.

설정·환경 변수 값은 싣지 않는다 — 실으면 CI 러너와 로컬에서 떨군 openapi 바이트가 갈린다. 드라이버·덤프·턴 기록의 원래 줄은
키를 바꾸지 않고 `dict` 그대로 싣는다(원문을 보이는 도구라 이름을 고치면 원문과 대조할 수 없다)."""

from typing import Any, Literal

from pydantic import Field

from api.core.schema import CamelModel

# 묶음 형식 세대. `legacy` 는 턴 줄에 방 id 가 없는 옛 형식이라 목록에만 보이고 열지 않는다.
BundleFormat = Literal["current", "preMessageId", "legacy"]

# 결합 어긋남 — 목록의 불일치 수는 이것만 센다.
# missingDump: 덤프 파일이 있는데 그 턴의 응답 시도에 생성 덤프가 없다(서버 앞에서 거부된 시도는 정상이라 넣지 않는다).
# unmatchedRow: 턴 기록 행이 어느 시도의 응답 id 와도 맞지 않는다(재생성·편집·드라이버 밖 턴의 행).
# turnGap: 턴 번호가 건너뛰었다.
# statMismatch: 같은 턴의 드라이버 스탯과 턴 기록 스탯이 다르거나, 내보낸 스탯 정의와 방 스냅숏의 스탯 목록이 다르다.
# unmatchedDumpLine: 이 방의 덤프 줄이 어느 턴에도 붙지 않는다.
# unplacedLine: 드라이버 줄을 놓을 턴을 알 수 없다(턴 번호가 없는 턴 줄, 없는 턴을 가리키는 재생성·수정 줄).
# chatTurnsRoomMismatch: 짝으로 고른 턴 기록 파일이 다른 방의 것이라 행을 하나도 붙이지 않았다.
MismatchKind = Literal[
    "missingDump",
    "unmatchedRow",
    "turnGap",
    "statMismatch",
    "unmatchedDumpLine",
    "unplacedLine",
    "chatTurnsRoomMismatch",
]

# 주의 — 결합이 틀린 것은 아니지만 읽는 사람이 알아야 하는 것. 불일치 수에 넣지 않는다(정상 런에도 흔히 생긴다).
# placementEstimated: 백그라운드 덤프 줄의 턴 배치는 추정이다.
# roomShared: 같은 방을 쓰는 묶음이 여럿인데 이 묶음이 매니페스트로 같은 폴더 밖 짝 파일을 쓴다.
# incompleteLine: 기록 중이던 파일의 잘린 마지막 줄을 버렸다. unreadableLine: 읽지 못한 줄을 건너뛰었다.
# manifest: 매니페스트를 읽지 못했거나 그 항목을 버렸다. notDumpLine: 덤프로 고른 파일에 덤프 꼴이 아닌 줄이 있다.
# pricesChanged: 턴 기록을 내보낸 때의 단가표와 지금 단가표가 다르다(원가는 지금 표로 낸다).
# statDefsChanged: 방 스냅숏마다 스탯 목록이 다르거나 이름이 같은 스탯이 있어 이름 키 스탯을 id 로 되돌릴 수 없다 — 그 묶음의
# 스탯 대조를 건너뛴다(대조하면 거짓 불일치가 된다).
CautionKind = Literal[
    "placementEstimated",
    "roomShared",
    "incompleteLine",
    "unreadableLine",
    "manifest",
    "notDumpLine",
    "pricesChanged",
    "statDefsChanged",
]


class Mismatch(CamelModel):
    kind: MismatchKind
    turn: int | None = None
    detail: str


class Caution(CamelModel):
    kind: CautionKind
    turn: int | None = None
    detail: str


class RunListItem(CamelModel):
    """런 목록의 한 줄. 지원하지 않는 형식은 열지 않으므로 경로·형식·방 id 밖의 칸이 비어 있다."""

    run_id: str
    path: str
    # 대량 시도 폴더(`probes`) 아래 묶음이면 그 폴더까지의 경로 — 목록이 이 키로 접는다.
    group: str | None
    format: BundleFormat
    supported: bool
    room_id: str
    story_name: str | None = None
    turn_count: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    # 방 스냅숏의 실제 생성 모델(`effectiveChatModel`)과 덤프 생성 줄의 보낸 모델 id.
    effective_chat_models: list[str] = Field(default_factory=list)
    generation_models: list[str] = Field(default_factory=list)
    # 시도에 붙은 턴 기록 행의 원가 합. 턴 기록이 없으면 None("내보내기 필요").
    cost_usd: float | None = None
    # 붙은 행 가운데 단가표에 없는 모델의 호출 수 — 원가 합에서 빠진 호출이다.
    unpriced_calls: int | None = None
    has_snapshots: bool = False
    has_dump: bool = False
    has_chat_turns: bool = False
    mismatch_count: int | None = None
    caution_count: int | None = None
    # 묶음을 열다 실패했으면 그 까닭(그 묶음만 "열 수 없음"으로 보인다).
    open_error: str | None = None


class DriverStatChange(CamelModel):
    """드라이버 턴 줄의 `statChanges` 한 칸(보이는 스탯만, 이름 키)."""

    name: str
    value: float


class RecordedStatChange(CamelModel):
    """턴 기록 `stat_changes` 한 칸. 이름·숨김 여부는 내보낸 스탯 정의(없으면 방 스냅숏)에서 얻고, 둘 다 모르면 비운다."""

    id: str
    name: str | None
    hidden: bool | None
    before: float | None
    after: float | None


class TurnSummary(CamelModel):
    turn: int
    attempt_count: int
    supplemented: bool
    replaced: bool
    # 고른 시도에 응답이 없다(모든 시도가 유실·거부).
    lost: bool
    user_text: str | None
    shortcut: str | None
    reply_head: str
    reply_length: int
    driver_stat_changes: list[DriverStatChange]
    recorded_stat_changes: list[RecordedStatChange]
    ending: dict[str, Any] | None
    failure: str | None
    earlier_generation_dumps: int
    judgment_dumps: int
    background_dumps: int
    cost_usd: float | None
    mismatch_count: int


class SeriesPoint(CamelModel):
    turn: int
    value: float


class StatSeries(CamelModel):
    """스탯 하나의 턴별 값. 보이는 스탯은 드라이버 `roomAfter`(턴을 마친 뒤 값)에서, 숨김 스탯은 턴 기록에서 — 턴 기록에는 바뀐
    턴의 값만 있어 숨김 스탯은 바뀐 턴에만 점이 있다."""

    id: str
    name: str
    hidden: bool | None
    source: Literal["driver", "chatTurns"]
    points: list[SeriesPoint]


MarkerKind = Literal[
    "rebase",
    "check",
    "noteUpdate",
    "pause",
    "regenerate",
    "edit",
    "ending",
    "noteChange",
    "summaryUpdate",
    "failure",
]


class TimelineMarker(CamelModel):
    """타임라인 표지. 드라이버 줄에서 온 표지(rebase·check·noteUpdate·pause)의 `turn` 은 그 줄을 쓸 때까지 마친 턴 수(그 턴 뒤에
    놓인다), 재생성·수정은 교체한 턴, 나머지는 그 턴이다."""

    kind: MarkerKind
    turn: int
    detail: str | None = None


class RunCost(CamelModel):
    """`total_usd`·`unpriced_calls`·`missing_token_calls` 는 시도에 붙은 행만 센다. 「짝 없는 기록」의 원가는 `unmatched_usd` 로
    따로 싣는다 — 같은 방을 이어 친 다른 측정의 행이 섞일 수 있어 이 런의 원가에 더하지 않는다."""

    total_usd: float
    unmatched_usd: float
    unpriced_calls: int
    missing_token_calls: int
    prices_as_of_export: str
    prices_sha256_export: str
    prices_changed: bool


class UnmatchedRow(CamelModel):
    """「짝 없는 기록」 — 어느 시도에도 붙지 않은 턴 기록 행."""

    assistant_message_id: str | None
    kind: str | None
    turn_number: int | None
    cost_usd: float


class RunDetail(CamelModel):
    run: RunListItem
    meta: dict[str, Any] | None
    room_static: dict[str, Any] | None
    turns: list[TurnSummary]
    series: list[StatSeries]
    markers: list[TimelineMarker]
    # 드라이버 스탯과 턴 기록 스탯을 실제로 견준 (턴, 스탯) 수 — 0 이면 대조가 아무것도 보지 않은 것이다.
    stat_comparisons: int
    cost: RunCost | None
    unmatched_rows: list[UnmatchedRow]
    mismatches: list[Mismatch]
    cautions: list[Caution]


class CallCostView(CamelModel):
    call_site: str
    model: str
    prompt_tokens: int | None
    cached_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    thoughts_tokens: int | None
    # 단가표에 없는 모델이면 None.
    usd: float | None
    missing_tokens: bool
    # 생성 호출에만 있다. 판정·임베딩 호출은 None(기록 없음).
    first_token_ms: int | None
    stream_first_token_ms: int | None


class ChatTurnRecord(CamelModel):
    row: dict[str, Any]
    calls: list[CallCostView]
    cost_usd: float


class AttemptDetail(CamelModel):
    index: int
    selected: bool
    # 서버 앞에서 거부된 시도(HTTP 비200) — 덤프가 없는 것이 정상이다.
    server_rejected: bool
    record: dict[str, Any]
    generation_dump: dict[str, Any] | None
    chat_turns: list[ChatTurnRecord]


class BackgroundDump(CamelModel):
    record: dict[str, Any]
    # turnField: 줄의 턴 칸을 따랐다. previousGeneration: 턴 칸이 없어 파일 순서상 바로 앞 생성 줄의 턴에 놓았다.
    placement: Literal["turnField", "previousGeneration"]


# 대화록 분석 판정(`analyze_chat_probe.ReplyFlags`)과 같은 칸. 고정 대본 키워드에 묶인 판정은 싣지 않는다 — 클래스 설명은
# openapi 스키마에 그대로 실리므로 여기 주석으로 둔다.
class ReplyFlagsView(CamelModel):
    length: int
    sentence_count: int
    truncated: bool
    self_copy: bool
    solicit: bool
    ignored: bool
    scene_open: bool
    label_leak: bool
    user_turn: bool
    broken: str | None
    brackets: list[str]


# 자기복제 판정이 견준 직전 응답: 오프닝, 앞 턴의 고른 시도, 앞 턴의 교체 뒤 응답, 없음(오프닝도 없는 로그).
PreviousFrom = Literal["opening", "turn", "replacement", "none"]


class TurnMetrics(CamelModel):
    turn: int
    flags: ReplyFlagsView
    previous_from: PreviousFrom
    previous_turn: int | None


class RunMetrics(CamelModel):
    """런 단위 요약. `scored` 가 표본 수(응답이 있는 턴)이고 셈은 모두 그 표본 안의 턴 수다."""

    scored: int
    lost: int
    truncated: int
    self_copy: int
    solicit: int
    ignored: int
    scene_open: int
    label_leak: int
    user_turn: int
    broken: int
    brackets: int
    median_length: float | None
    median_sentences: float | None
    # 응답 길이가 끝까지 늘지 않았는가(방 단위 판정). 표본이 없으면 None.
    length_non_increasing: bool | None
    turns: list[TurnMetrics]


class TurnDetail(CamelModel):
    turn: int
    supplemented: bool
    replaced: bool
    attempts: list[AttemptDetail]
    earlier_generation_dumps: list[dict[str, Any]]
    judgment_dumps: list[dict[str, Any]]
    background_dumps: list[BackgroundDump]
    replacements: list[dict[str, Any]]
    # 이 턴에 보낸 기억(이 턴 이하의 마지막 스냅숏). `memory_snapshot_changed_here` 는 그 스냅숏이 이 턴에 새로 남았는가.
    memory_snapshot: dict[str, Any] | None
    memory_snapshot_changed_here: bool
    metrics: TurnMetrics | None
    mismatches: list[Mismatch]
    cautions: list[Caution]
    # 이 화면이 보여 줄 수 없는 것을 사실대로 적은 문장들.
    record_limits: list[str]
