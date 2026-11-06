import { axisNames, CLAUDE_MODEL_AXES } from "./axes";
import type {
  CheckErrorKind,
  CredentialProvider,
  CredentialState,
  CredentialStateReason,
  EnableBlocker,
} from "./credential";
import type { CredentialStatus, EnvRouteCause, UnverifiedCause } from "./status";

export const PROVIDER_LABELS = {
  anthropic: "Anthropic",
  bedrock: "Bedrock",
} as const satisfies Record<CredentialProvider, string>;

export const PAGE_INTRO_TEXT =
  "Anthropic 계정 키를 순서대로 둬요. 목록이 실제로 쓰이는 동안 모델마다 위에서부터 받을 수 있는 첫 항목으로 호출이 나가고, 그 계정이 크레딧·키·한도로 막히면 다음 항목으로 넘어가요. 새 항목은 꺼진 채 목록 끝에 들어가요 — 확인 호출이 통과한 뒤 켜요.";

export const LIST_LOAD_ERROR_TEXT = "Claude 자격 목록을 불러오지 못했어요.";

export const STORE_MISSING_TEXT =
  "자격 저장소 설정이 없어요. 키 추가·키 교체·확인 호출·목록 사용 켜기는 서버 env 의 암호화 키 목록(LLM_CREDENTIAL_ENCRYPTION_KEYS)과 허용 계정(LLM_CREDENTIAL_ALLOWED_ACCOUNTS)이 있어야 해요. 끄기·삭제·순서·이름 수정·목록 사용 끄기는 지금도 돼요.";

export const NOTIFICATIONS_MISSING_TEXT = "알림 웹훅이 없어 변경·소진 알림이 Discord 로 가지 않아요.";

export const EMPTY_LIST_TEXT =
  "아직 자격이 없어요. 자격을 추가하면 꺼진 채 목록 끝에 들어가고, 확인 호출이 통과한 뒤 켤 수 있어요.";

export const SPEND_CAUTION_TEXT =
  "추정 사용액은 목록으로 나간 호출과 확인 호출만 단가표로 친 값이에요. 목록을 쓰지 않은 동안 env 키로 나간 호출, 같은 키로 다른 곳에서 부른 호출, 끝까지 받지 못한 호출은 빠져 실제 잔액보다 많게 보일 수 있어요. 콘솔 잔액을 보고 ‘충전액 맞추기’로 고쳐 주세요.";

export const UNREADABLE_SECRET_SCOPE_TEXT =
  "저장한 키를 서버가 읽을 수 없게 된 항목은 이 목록에 따로 표시되지 않아요 — 런타임이 건너뛰고 Discord 로 알려요. 의심되면 그 항목을 확인 호출해 보세요.";

export const BEDROCK_UNSUPPORTED_TEXT = "Bedrock 항목의 키 교체·확인 호출은 아직 없어요.";

/** 실효 경로가 env 키인 원인 문장. 목록 사용 절의 경로 줄이 "env 키로 나가요" 뒤에 붙인다(목록이 빈 경우는 문장 꼴이 달라 따로 둔다). */
export const ENV_ROUTE_CAUSE_LABELS = {
  "switch-off": "서버 스위치 ‘Claude 자격 목록’(LLM_CREDENTIAL_POOL_ENABLED)이 꺼져 있어요. 서버 env 로만 켜요.",
  "pool-off": "어드민 목록 사용이 꺼져 있어요.",
  "store-missing": "서버에 자격 저장소 설정이 없어요.",
  "notifications-missing": "서버에 알림 웹훅 설정이 없어요.",
} as const satisfies Record<Exclude<EnvRouteCause, "empty">, string>;

export const LIST_ROUTE_TEXT =
  "지금 Claude 호출은 이 목록으로 나가요 — 모델마다 아래 순서에서 받을 수 있는 첫 항목이에요. 받을 항목이 없는 모델은 env 키로 넘어가지 않고 실패·환불돼요.";

export function envRouteText(cause: EnvRouteCause): string {
  return cause === "empty" ? "목록이 비어 env 키로 나가요." : `지금 Claude 호출은 env 키로 나가요 — ${ENV_ROUTE_CAUSE_LABELS[cause]}`;
}

export const SWITCH_PENDING_TEXT = "서버 스위치 값을 읽는 중이에요.";
export const SWITCH_FAILED_TEXT = "서버 스위치 값을 읽지 못해 지금 호출 경로를 단정할 수 없어요.";

const EXHAUSTED_REASON_LABELS = {
  credit: "크레딧",
  auth: "키 무효(폐기·조직 비활성)",
  limit: "지출 한도",
} as const satisfies Record<Exclude<CredentialStateReason, "admin">, string>;

const UNVERIFIED_CAUSE_LABELS = {
  "provider-unsupported": "이 공급자는 아직 쓰지 않아요",
  "organization-unverified": "조직 확인 전",
  "account-not-allowed": "허용 목록 밖 조직",
  "organization-mismatch": "응답 조직 불일치(그 모델이 조직이 맞는 통과를 다시 받아야 풀려요)",
  // 켜진 항목의 켜기 막힘은 대개 확인 필요다(켜는 순간 판이 오른다) — 조직 신호가 그 값 뒤에 가려질 수 있어 원인을 단정하지 않는다.
  "no-servable-axis": "지금 키로 받을 수 있는 모델 없음 — 확인 결과를 보세요",
} as const satisfies Record<UnverifiedCause, string>;

/** 상태 표지의 글자. 뜻은 늘 글자가 진다 — 색·아이콘은 덧붙임이다. */
export function credentialStatusText(status: CredentialStatus): string {
  switch (status.kind) {
    case "serving":
      return status.axes.length < CLAUDE_MODEL_AXES.length ? `사용 중 · ${axisNames(status.axes)}` : "사용 중";
    case "standby":
      return status.axes.length < CLAUDE_MODEL_AXES.length ? `대기 · ${axisNames(status.axes)}만` : "대기";
    case "unverified":
      return `미확인 · ${UNVERIFIED_CAUSE_LABELS[status.cause]}`;
    case "exhausted":
      // 꺼짐 사유(admin)나 사유 없음은 소진에 오지 않는 값이라 사유 없이 둔다.
      return status.reason === null || status.reason === "admin"
        ? "소진"
        : `소진 · ${EXHAUSTED_REASON_LABELS[status.reason]}`;
    case "disabled":
      // 꺼짐은 언제나 운영자가 끈 것이거나 새 항목이라 사유를 붙이지 않는다.
      return status.neverChecked ? "꺼짐 · 확인 전" : "꺼짐";
    default:
      return assertNever(status);
  }
}

/** 확인 결과 한 칸의 글자. 일시 오류는 이전 결과와 함께 읽어야 해서 부르는 쪽(`checkResultText`)이 따로 다룬다. */
const CHECK_ERROR_LABELS = {
  credit: "실패 — 크레딧 부족. 콘솔에서 충전한 뒤 다시 확인하세요",
  auth: "실패 — 키가 거부됐어요(무효·폐기·조직 비활성)",
  limit: "실패 — 지출 한도에 걸렸어요. 콘솔의 한도를 확인하세요",
  permission: "실패 — 이 모델을 쓸 권한이 없어요(403)",
  "model-not-found": "실패 — 이 계정에서 이 모델 id 를 찾을 수 없어요(404)",
  rejected: "실패 — Anthropic 이 요청 형태를 거부했어요. 서버 로그를 확인해야 해요",
  unavailable: "일시 오류",
  "organization-mismatch": "실패 — 응답의 조직이 저장된 조직과 달라요. 이 키가 맞는 계정의 키인지 확인하세요",
  "account-not-allowed": "실패 — 응답의 조직이 허용 목록 밖이에요",
  "account-already-listed": "실패 — 이 조직의 키가 이미 다른 항목으로 목록에 있어요",
} as const satisfies Record<CheckErrorKind, string>;

/** 확인 행 하나의 결론 글자(통과·실패 사유). 일시 오류 행에는 "일시 오류"만 돌려준다. */
export function checkVerdictText(check: { passed: boolean; errorKind: CheckErrorKind | null }): string {
  if (check.passed) return "통과";
  return check.errorKind === null ? "실패" : CHECK_ERROR_LABELS[check.errorKind];
}

export const TRANSIENT_WITH_PREVIOUS_TEXT = "일시 오류 — 이전 결과 유지";
export const TRANSIENT_WITHOUT_PREVIOUS_TEXT = "일시 오류 — 이 키로 한 이전 결과가 없어 이 모델은 아직 쓰지 않아요";
export const TRANSIENT_RETRY_HINT_TEXT = "1분 뒤 다시 확인하세요";
export const OLD_SECRET_CHECK_TEXT = "키를 바꾸기 전에 한 확인이에요 — 지금 키로 다시 확인해야 써요.";
export const RETURNED_SECRET_CHECK_TEXT = "지금 키로 예전에 한 확인 결과를 써요 — 키를 바꾸기 전에 한 최신 확인은 세지 않아요.";
export const OLD_STATE_CHECK_TEXT = "상태가 바뀌기 전에 한 확인이라 켜기 조건에 세지 않아요.";
export const ENABLE_NEEDS_CONCLUSIVE_TEXT =
  "켜려면 최신 확인이 일시 오류 없이 통과해야 해요 — 켜기 조건은 이전 결과로 내려가지 않아요.";
export const NO_CHECKS_TEXT = "아직 확인하지 않았어요 — 켜기 전에 확인 호출이 필요해요.";

export function modelIdChangedText(sentModelId: string, currentModelId: string | undefined): string {
  return `모델 id 설정(${sentModelId} → ${currentModelId ?? "알 수 없음"})이 바뀐 뒤 확인하지 않았어요 — 목록 사용을 켜려면 다시 확인해야 해요.`;
}

/** 켜기·다시 켜기를 막는 이유. 409 로 왔을 때도 같은 문장이다. 확인 필요는 문장 뒤에 같은 항목의 확인 호출로 가는 버튼이 붙는다. */
export function enableBlockerText(blocker: EnableBlocker, state: CredentialState): string {
  switch (blocker) {
    case "organization-unverified":
      return "조직을 확인하지 못해 켤 수 없어요. 확인 호출이 응답 헤더로 조직을 다시 대조해요.";
    case "account-not-allowed":
      return "이 항목의 조직이 지금 서버 허용 목록에 없어 켤 수 없어요.";
    case "check-required":
      return state === "exhausted"
        ? "충전하거나 한도를 푼 뒤 확인 호출이 통과해야 다시 켤 수 있어요. 소진되기 전에 한 확인은 세지 않아요."
        : "지금 키로, 지금 상태에서 한 확인 호출이 통과해야 켤 수 있어요.";
    case "organization-mismatch":
      // 조직이 어긋났던 축은 응답 조직이 맞는 통과를 다시 받아야만 풀린다 — 일시 오류나 조직과 무관한 실패로는 풀리지 않는다.
      return "응답의 조직이 어긋났던 모델이 아직 조직이 맞는 통과를 다시 받지 않아 켤 수 없어요. 그 모델이 확인 호출에서 응답 조직이 맞는 통과를 받아야 풀려요 — 이 키가 맞는 계정의 키인지도 확인하세요.";
    default:
      return assertNever(blocker);
  }
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 값: ${String(value)}`);
}
