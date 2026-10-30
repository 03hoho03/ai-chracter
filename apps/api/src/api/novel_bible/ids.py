"""정본 기억의 이름 공간 — 값이 정해진 칸의 값 목록.

정본 기억 표(`db/models/novel_bible*.py`)의 CHECK 값 목록은 여기 Literal 에서 만든다. 값 목록을 두 곳에 적으면 한쪽만
고쳐지기 쉽다. 모델 모듈이 이 모듈을 import 하므로 typing 밖의 것을 import 하지 않는다 — 여기서 앱 코드를 끌어오면 그
코드가 모델을 다시 import 해 순환이 생긴다. 이 모듈을 import 하면 패키지 `__init__.py` 가 먼저 실행되므로 그 파일도 아무것도
import 하지 않는다 — 엔진 코드를 거기서 다시 내보내면 그 코드가 모델을 import 해 같은 순환이 생긴다.

🔴 `alembic check` 는 CHECK 제약을 비교하지 않는다. 값을 더하거나 빼면 CHECK 를 바꾸는 마이그레이션을 손으로 쓴다(넓히기가
먼저다 — 새 값을 쓰는 코드보다 CHECK 가 먼저 넓어야 한다)."""

from typing import Literal

# 슬롯 id — 작업 표의 `slot` CHECK 와 같은 넷이다. 슬롯 코드가 하나씩 들어와도 DB 는 처음부터 넷을 받는다.
SlotId = Literal["source", "events", "facts", "knowledge"]
# 모델 호출 하나를 어댑터에 배정하는 단위 — 추출은 슬롯마다, 판정은 충돌 검사 하나. 슬롯은 자기 추출의 이름을 갖고 코어는 이
# 이름으로 어댑터를 받는다(어느 모델인지는 모른다).
OperationKey = Literal["events.extract", "facts.extract", "knowledge.extract", "conflicts.judge"]
ItemTable = Literal["event", "event_relation", "fact", "knowledge", "adaptation_candidate"]
# 항목 표의 상태. `confirmed` 밖의 값은 자리만 잡아 둔 것이다. 대체는 상태 값이 아니라 만료 행과 새 행의 `supersedes_id` 로
# 나타낸다 — 항목 행은 넣은 뒤 고치지 않는다.
ItemStatus = Literal["confirmed", "proposed", "approved_for_revision", "needs_alignment", "planned"]
CommitStatus = Literal["pending", "extracting", "linking", "checking", "committed", "blocked", "failed", "stale"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]
FactKind = Literal["life", "presence", "possession", "ability", "attribute", "relation"]
# 사건이 이야기 안에서 실제로 일어났는가. 꿈·상상 사건은 상태 계산과 차단 규칙 어디에도 참으로 들어가지 않는다.
EventActuality = Literal["present", "flashback", "dream_or_imagined"]
CommitKind = Literal["chapter_confirm", "direct_edit"]
ActorKind = Literal["admin", "system", "user"]
CommitFailure = Literal["slot_failed", "cas_exhausted", "chapter_gone", "stalled", "internal"]
JobFailure = Literal[
    "schema_invalid",
    "truncated",
    "empty",
    "blocked",
    "llm_error",
    "rate_limited",
    "cancelled",
    "internal",
    "expired",
    "prompt_missing",
    "input_too_large",
]
EntityKind = Literal["character", "object", "ability"]
EvidenceOrigin = Literal["manuscript_block", "chat_message", "chat_memory", "source_canon"]
SourceField = Literal["work_setting", "keyword_note"]
ExpirationReason = Literal["chapter_replaced", "edited"]
AdaptationOrigin = Literal["source_canon", "play"]
AdaptationStatus = Literal["open", "accepted", "rejected"]
EventRelationKind = Literal["before", "after", "overlap"]
FactScope = Literal["work", "from_here", "scene"]
LifeValue = Literal["alive", "dead"]
# 떠남(돌아올 수 있음)과 영구 퇴장을 가른다.
PresenceValue = Literal["present", "departed", "gone_for_good"]
KnowledgeKind = Literal["knows", "believes"]
FindingSeverity = Literal["block", "warning"]
# 검사 결과 이름. 차단 이름과 경고 이름을 따로 두어, 경고만 내는 단계가 낼 수 있는 이름을 타입이 말하게 한다. 중첩 Literal 은
# `get_args` 가 평평한 값 열로 돌려주므로 검사 결과 표의 CHECK 는 `FindingRule` 하나에서 만든다.
BlockingRule = Literal[
    "exit_then_appearance", "use_before_acquisition", "knowledge_before_fact", "immutable_attribute_mismatch"
]
WarningRule = Literal[
    "order_undetermined",
    "use_without_acquisition",
    "use_after_loss",
    "knowledge_source_unclear",
    "return_unstated",
    "onset_unstated",
    "evidence_unverified",
    "attribute_surface_differs",
    "llm_conflict",
    "judge_failed",
]
FindingRule = Literal[BlockingRule, WarningRule]
