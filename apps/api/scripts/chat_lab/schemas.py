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
# chatTurnsNotJoined: `assistantMessageId` 이전 형식이라 턴 기록 행을 붙일 응답 id 가 없어 행을 턴에 잇지 않았다 — 원가도 내지
# 않는다(붙은 행이 없다).
CautionKind = Literal[
    "placementEstimated",
    "roomShared",
    "incompleteLine",
    "unreadableLine",
    "manifest",
    "notDumpLine",
    "pricesChanged",
    "statDefsChanged",
    "chatTurnsNotJoined",
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
    # 실제 생성 모델(방 스냅숏의 `effectiveChatModel`, 스냅숏에 없으면 턴 기록 파일의 행 전부의 `chat_model`)과 덤프 생성 줄의
    # 보낸 모델 id.
    effective_chat_models: list[str] = Field(default_factory=list)
    generation_models: list[str] = Field(default_factory=list)
    # 시도에 붙은 턴 기록 행의 원가 합. 턴 기록이 없으면 None("내보내기 필요").
    cost_usd: float | None = None
    # 붙은 행 가운데 단가표에 없는 모델의 호출 수 — 원가 합에서 빠진 호출이다.
    unpriced_calls: int | None = None
    # 원가 합이 실제보다 낮을 수 있다 — 붙은 행에 단가 없는 호출이나 입력 토큰이 기록되지 않은 호출이 있다(턴 요약과 같은 판정).
    # 원가가 없으면 None.
    cost_is_lower_bound: bool | None = None
    has_snapshots: bool = False
    has_dump: bool = False
    has_chat_turns: bool = False
    mismatch_count: int | None = None
    caution_count: int | None = None
    # 묶음을 열다 실패했으면 그 까닭(그 묶음만 "열 수 없음"으로 보인다).
    open_error: str | None = None


class DriverStatChange(CamelModel):
    """드라이버 턴 줄의 `statChanges` 한 칸(보이는 스탯만, 이름 키). `value` 는 변화량이 아니라 바뀐 뒤 값이다 — 드라이버가 SSE
    `statChange` 의 새 값(`newValue`)을 적는다. 변화량은 서버가 그 턴이 시작한 값(`before`)과 함께 낸다(`delta`).

    시작 값은 리플레이가 그 턴을 조립할 때 읽는 스탯 줄(그 턴 줄 앞에서 방 턴 수가 하나 작은 마지막 오프닝·턴·기준 다시 잡기·대조
    줄)의 같은 이름 값이다. 첫 턴은 오프닝, 보통은 앞 턴에서 고른 시도의 줄(사람이 친 턴을 보충한 줄이어도 같다), 앞 턴이 유실된
    뒤 드라이버가 기준을 다시 잡았으면 그 줄이다. 같은 턴의 시도는 고르지 않은 것까지 모두 이 값에서 시작한다(같은 상태에서
    보냈다). 그런 줄이 없으면(앞 턴이 재시도 없이 유실됐거나 턴 번호가 건너뛰었는데 기준을 다시 잡은 줄도 없다) 비고, 앞 턴의
    응답을 재생성·수정이 바꿨어도 빈다 — 교체 줄에는 바뀐 뒤 스탯이 없고 재생성은 스탯을 다시 판정한다."""

    name: str
    value: float = Field(description="바뀐 뒤 값(SSE statChange 의 새 값). 변화량이 아니다.")
    before: float | None = Field(description="그 턴이 시작한 값. 기록으로 알 수 없으면 null.")
    delta: float | None = Field(description="value − before. before 가 null 이면 null.")


class RecordedStatChange(CamelModel):
    """턴 기록 `stat_changes` 한 칸. 이름·숨김 여부는 내보낸 스탯 정의(없으면 방 스냅숏)에서 얻고, 둘 다 모르면 비운다."""

    id: str
    name: str | None
    hidden: bool | None
    before: float | None
    after: float | None


# 대화록 분석 판정(`analyze_chat_probe.ReplyFlags`)과 같은 칸. 고정 대본 키워드에 묶인 판정은 싣지 않는다 — 클래스 설명은
# openapi 스키마에 그대로 실리므로 여기 주석으로 둔다. 길이·문장 수는 응답 끝의 상태창 코드 블록을 뗀 본문이고, 뗀 꼬리의 글자
# 수가 `status_block_length`(없으면 0)다 — 떼는 규칙은 `analyze_chat_probe.reply_flags`.
class ReplyFlagsView(CamelModel):
    length: int
    sentence_count: int
    status_block_length: int
    truncated: bool
    self_copy: bool
    solicit: bool
    ignored: bool
    scene_open: bool
    label_leak: bool
    user_turn: bool
    broken: str | None
    brackets: list[str]


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
    # 응답 단위 플래그 — 런 지표의 같은 턴 칸(`TurnMetrics.flags`) 그대로다. 응답이 없는 턴은 None.
    flags: ReplyFlagsView | None
    # 그 턴의 시도에 붙은 턴 기록 행의 원가 합. 붙은 행이 없으면(턴 기록 파일이 없는 경우 포함) None.
    cost_usd: float | None
    # 합에 단가 없는 호출이나 입력 토큰이 기록되지 않은 호출이 섞여, 합이 실제 원가보다 낮을 수 있다.
    cost_is_lower_bound: bool
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


# 호출 종류(`report.call_site_kind`). generation: 본문을 스트리밍으로 쓰는 생성(채팅 응답·미리보기·소설 화·리플레이). judgment:
# 판정(스탯·엔딩·그림·장면 헤더). background: 요약 접기와 기억 추출·인상 — 응답 뒤에 돈다. embedding: 기억 임베딩(질의·저장).
# other: 그 밖(심사·시드·소설 구조화 호출 — 채팅 턴 기록에는 없다)과 모르는 이름.
CallSiteKind = Literal["generation", "judgment", "background", "embedding", "other"]


class CallCostView(CamelModel):
    call_site: str
    kind: CallSiteKind
    model: str
    prompt_tokens: int | None
    cached_tokens: int | None
    cache_write_tokens: int | None
    output_tokens: int | None
    thoughts_tokens: int | None
    # 정가로 치는 입력 토큰 — 입력 − 캐시 읽기 − 캐시 쓰기(음수면 0). 입력 토큰이 기록되지 않았으면 None.
    new_input_tokens: int | None
    # 단가표에 없는 모델이거나 입력 토큰이 기록되지 않은 호출이면 None — 원가를 모르는 호출을 0 원으로 보이지 않는다.
    usd: float | None
    missing_tokens: bool
    # 생성 호출에만 있다. 판정·임베딩 호출은 None(기록 없음).
    first_token_ms: int | None
    stream_first_token_ms: int | None


class ChatTurnRecord(CamelModel):
    row: dict[str, Any]
    calls: list[CallCostView]
    cost_usd: float
    # 이 행에 단가 없는 호출이나 입력 토큰이 기록되지 않은 호출이 있어 `cost_usd` 가 실제 원가보다 낮을 수 있다.
    cost_is_lower_bound: bool


class AttemptDetail(CamelModel):
    index: int
    selected: bool
    # 서버 앞에서 거부된 시도(HTTP 비200) — 덤프가 없는 것이 정상이다.
    server_rejected: bool
    record: dict[str, Any]
    # 이 시도 줄의 스탯 변화. 시작 값은 고른 시도와 같다(`DriverStatChange`).
    driver_stat_changes: list[DriverStatChange]
    generation_dump: dict[str, Any] | None
    chat_turns: list[ChatTurnRecord]


class BackgroundDump(CamelModel):
    record: dict[str, Any]
    # turnField: 줄의 턴 칸을 따랐다. previousGeneration: 턴 칸이 없어 파일 순서상 바로 앞 생성 줄의 턴에 놓았다.
    placement: Literal["turnField", "previousGeneration"]


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


# 기록 한계 문장이 대신 서는 자리. judgmentResponse: 판정 응답 원문. judgmentLatency: 판정·임베딩 호출의 지연. backgroundTokens:
# 백그라운드 호출의 토큰·원가. exportNeeded: 턴 기록 파일이 없어 비는 토큰·원가(`assistantMessageId` 이전 형식에는 없다 — 내보내기를
# 거부한다). promptDump: 덤프가 없어 비는 프롬프트·지시문 원문.
RecordLimitSlot = Literal["judgmentResponse", "judgmentLatency", "backgroundTokens", "exportNeeded", "promptDump"]


class RecordLimit(CamelModel):
    """이 화면이 보여 줄 수 없는 것을 사실대로 적은 문장 하나와, 그 문장이 대신 서는 자리."""

    slot: RecordLimitSlot
    text: str


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
    record_limits: list[RecordLimit]


class Health(CamelModel):
    status: Literal["ok"]


class RunList(CamelModel):
    """런 목록. 서버는 루트를 한 번 훑은 결과를 들고 있다가 `refresh` 로 다시 훑는다 — `discovered_at` 은 그 탐색 시각이고, 그 뒤
    새로 생긴 묶음은 다시 훑어야 보인다. 이미 찾은 묶음의 파일이 바뀐 것은 다시 훑지 않아도 반영된다."""

    items: list[RunListItem]
    discovered_at: str


class RunBundle(CamelModel):
    """런 하나를 통째로 — 정적 HTML 내보내기가 이 응답만 주입한다. `raw` 가 거짓이면 덤프 줄의 프롬프트(`prompt`)·지시문
    (`systemInstruction`)과 기억 스냅숏의 노트·요약 본문(`note`·`summary`) 칸을 키째 뺀다. 대화(사용자 발화·응답)는 남는다."""

    raw: bool
    detail: RunDetail
    metrics: RunMetrics
    turns: list[TurnDetail]


class ExportTurnsRequest(CamelModel):
    # 참이면 이미 있는 턴 기록 파일을 새로 내보낸 것으로 바꾼다.
    force: bool


class ExportTurnsResult(CamelModel):
    # 쓴 턴 기록 파일의 런 루트 기준 경로, 그리고 그 파일을 짝으로 다시 읽은 목록 항목.
    path: str
    run: RunListItem


# 이 서버가 내는 오류의 종류. FastAPI 의 요청 검증 오류(422, `detail` 이 목록)에는 이 칸이 없어 웹은 `reason` 으로 둘을 가른다.
# notFound: 그런 묶음·턴이 없다(id 모양이 틀린 것 포함). unsupported: 열지 않는 형식. openFailed: 열다 실패했다.
# unsupportedFormat: `assistantMessageId` 이전 형식이라 턴 기록을 응답과 이을 열쇠가 없어 내보내도 이을 수 없다(내보내기만).
# archived: 보관 폴더라 쓰지 않는다. exists: 턴 기록 파일이 이미 있다 — 강제로 다시 내보낼 수 있는 것은 이것뿐이다.
# notFile: 그 자리에 링크·폴더가 있다. noRoom·noRows: 그 DB 에 방이 없거나 턴 기록이 0 이다. multipleRooms: 묶음 폴더에 서로
# 다른 방의 드라이버 로그가 있다. dbUnavailable: DB 가 설정되지 않았거나 닿지 않는다. notJson: 쓰기 요청 본문이 JSON 이 아니다.
LabErrorReason = Literal[
    "notFound",
    "unsupported",
    "unsupportedFormat",
    "openFailed",
    "archived",
    "exists",
    "notFile",
    "noRoom",
    "noRows",
    "multipleRooms",
    "dbUnavailable",
    "notJson",
]


class LabError(CamelModel):
    detail: str
    reason: LabErrorReason
