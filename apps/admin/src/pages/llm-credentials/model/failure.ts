import type { ApiError } from "@ai-character-chat/api-types";

import { apiErrorCode, isApiError } from "@/shared/lib/api/client";

import { axisNames, isClaudeModelAxis } from "./axes";
import { CHECK_COOLDOWN_SECONDS } from "./checkCall";
import type { ClaudeModelAxis, CredentialState, EnableBlocker } from "./credential";
import { BEDROCK_UNSUPPORTED_TEXT, enableBlockerText, STORE_MISSING_TEXT } from "./labels";

/** 폼 칸 이름. 서버 422 검증 목록의 칸 이름(`loc` 의 끝)과 같다. */
export type CredentialFormField = "label" | "apiKey" | "creditUsd" | "alertPct";

/**
 * 자격 쓰기 실패를 화면이 할 일로 가른다. 문구는 여기서 정하고(서버 `message` 는 모르는 거절일 때만 쓴다), 무엇을 할지는 `kind` 가
 * 정한다.
 * - `secret-rejected`: 붙여넣은 키가 틀렸다 — 키 칸에 오류를 걸고 칸을 비운 뒤 포커스.
 * - `upstream-unavailable`: Anthropic 에 닿지 못했다 — 키가 틀린 게 아니라 칸을 비우지 않는다.
 * - `stale-order`: 화면이 본 목록 판이 낡았다 — 확인 대화상자가 열려 있으면 닫고 순서 절 위에 안내한다.
 * - `fields`: 서버 검증이 칸을 거절했다(서버는 입력값을 되돌려 싣지 않는다).
 * - `unknown-outcome`: 서버 오류이거나 응답 없이 끊겼다(연결은 살아 있다) — 커밋 뒤에 응답만 끊겼을 수 있어 실패로 단정하지 않고,
 *   목록을 다시 받아 실제 결과를 보게 한다.
 * 목록을 다시 받아야 하는 실패는 `failureReloadsList` 가 고른다 — 뮤테이션이 실패마다 이미 그렇게 한다.
 */
export type CredentialFailure =
  | { kind: "store-missing"; message: string }
  | { kind: "secret-rejected"; message: string }
  | { kind: "upstream-unavailable"; message: string }
  | { kind: "stale-order"; message: string }
  | { kind: "pool-uncovered"; axes: ClaudeModelAxis[]; message: string }
  | { kind: "enable-blocked"; blocker: EnableBlocker; message: string }
  | { kind: "secret-unreadable"; message: string }
  | { kind: "rate-limited"; retryAfterSeconds: number; message: string }
  | { kind: "not-found"; message: string }
  | { kind: "conflict"; message: string }
  | { kind: "fields"; fields: CredentialFormField[]; message: string }
  | { kind: "offline"; message: string }
  | { kind: "unknown-outcome"; message: string }
  | { kind: "other"; message: string };

export type FailureContext = {
  /** 허용 목록 밖 키 거절에 "운영 알림이 갔어요"를 붙일지. 서버는 거절 전에 알림을 쏘지만 웹훅이 없으면 경고 로그만 남는다. */
  notificationsConfigured?: boolean;
  /** 켜기 막힘 문장이 꺼짐·소진에 따라 갈린다. */
  credentialState?: CredentialState;
};

/** 자격 쓰기의 거절 `rule`. 거절 본문(`detail: {rule, message, …}`)은 OpenAPI 에 실리지 않아 생성 타입이 없어 서버 라우터·저장 구간의
 * 거절을 여기 옮겨 적는다. */
type CredentialRule =
  | "store-not-configured"
  | "secret-format"
  | "credential-rejected"
  | "upstream-unavailable"
  | "account-not-allowed"
  | "account-already-listed"
  | "account-mismatch"
  | "provider-not-available"
  | "stale-list-revision"
  | "order-mismatch"
  | "pool-uncovered"
  | "credit-basis-missing"
  | "organization-unverified"
  | "check-required"
  | "organization-mismatch"
  | "secret-unreadable"
  | "conflict";

/** 확인 호출의 항목별 레이트리밋 거절 code. */
const CHECK_LIMIT_CODE = "LLM_CREDENTIAL_CHECK_LIMIT";

const GENERIC_FAILURE_TEXT = "저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
const UNKNOWN_OUTCOME_TEXT = "결과를 받지 못했어요 — 목록을 다시 받아 확인해 주세요.";
const OFFLINE_FAILURE_TEXT = "서버에 닿지 못했어요. 연결을 확인한 뒤 다시 눌러 주세요. (보내지 않았어요)";
const FIELDS_FAILURE_TEXT = "입력값을 확인해 주세요.";
const STALE_ORDER_TEXT =
  "다른 곳에서 목록이 먼저 바뀌었어요(추가·삭제·순서). 최신 목록을 다시 불러왔어요 — 순서를 확인하고 다시 옮겨 주세요.";

/** 키를 저장할 때 판정 모델 id 로 토큰 세기를 불러 조직을 보는데, 그 호출이 거절된 종류(`credential-rejected` 의 `reason`). */
type RejectedReason = "credit" | "auth" | "limit" | "permission" | "model-not-found" | "rejected";

const REJECTED_REASON_TEXTS = {
  credit: "크레딧이 부족해 Anthropic 이 키를 받지 않았어요. 충전한 뒤 다시 넣어 주세요. (저장하지 않았어요)",
  auth: "키가 무효이거나 조직이 비활성이에요. (저장하지 않았어요)",
  limit: "지출 한도에 걸린 키예요. 콘솔에서 한도를 확인한 뒤 다시 넣어 주세요. (저장하지 않았어요)",
  permission: "이 키로는 판정 모델을 쓸 권한이 없어요(403). (저장하지 않았어요)",
  "model-not-found": "이 키의 계정에서 판정 모델 id 를 찾을 수 없어요(404). (저장하지 않았어요)",
  rejected: "Anthropic 이 요청을 거부했어요. (저장하지 않았어요)",
} satisfies Record<RejectedReason, string>;

const RULE_FAILURES = {
  "store-not-configured": () => ({ kind: "store-missing", message: STORE_MISSING_TEXT }),
  "secret-format": () => ({
    kind: "secret-rejected",
    message: "키 형식이 아니에요. 공백·줄바꿈 없이 20~256자여야 해요.",
  }),
  "credential-rejected": (error) => {
    const reason = detailString(error, "reason");
    const known = reason !== undefined && isRejectedReason(reason) ? REJECTED_REASON_TEXTS[reason] : undefined;
    return { kind: "secret-rejected", message: known ?? serverMessage(error) ?? GENERIC_FAILURE_TEXT };
  },
  "upstream-unavailable": () => ({
    kind: "upstream-unavailable",
    message: "Anthropic 에 닿지 못했어요. 잠시 뒤 다시 시도해 주세요. (저장하지 않았어요)",
  }),
  // 같은 이름이 키 저장의 거절(422)과 켜기 막힘(409) 두 자리에서 온다.
  "account-not-allowed": (error, context) => {
    if (error.status === 409) return enableBlocked("account-not-allowed", context);
    const notified = context.notificationsConfigured === true ? " 운영 알림이 갔어요." : "";
    return { kind: "secret-rejected", message: `허용 목록 밖 조직의 키라 저장하지 않았어요.${notified}` };
  },
  "account-already-listed": () => ({
    kind: "secret-rejected",
    message: "이 조직의 키는 이미 목록에 있어요 — 한 조직에 항목 하나예요. 그 항목의 키를 교체하세요.",
  }),
  "account-mismatch": () => ({
    kind: "secret-rejected",
    message: "다른 조직의 키로는 바꿀 수 없어요. 이 항목을 지우고 새로 추가하세요.",
  }),
  "provider-not-available": () => ({ kind: "other", message: BEDROCK_UNSUPPORTED_TEXT }),
  // 판 검사가 집합 검사보다 먼저라 둘 다 "다른 곳에서 먼저 바뀌었다"의 뜻이다.
  "stale-list-revision": () => ({ kind: "stale-order", message: STALE_ORDER_TEXT }),
  "order-mismatch": () => ({ kind: "stale-order", message: STALE_ORDER_TEXT }),
  "pool-uncovered": (error) => {
    const axes = detailAxes(error);
    const subject = axes.length > 0 ? `${axisNames(axes)} 모델을` : "어떤 모델을";
    return {
      kind: "pool-uncovered",
      axes,
      message: `켤 수 없어요 — ${subject} 지금 키·지금 모델 id 로 확인 통과한 켜진 항목이 없어요. 그 모델을 받을 항목을 확인 호출한 뒤 켜세요.`,
    };
  },
  "credit-basis-missing": () => ({
    kind: "other",
    message: "충전액이 없어 기준을 다시 잡을 수 없어요. 충전액을 먼저 넣어 주세요.",
  }),
  "organization-unverified": (_error, context) => enableBlocked("organization-unverified", context),
  "check-required": (_error, context) => enableBlocked("check-required", context),
  "organization-mismatch": (_error, context) => enableBlocked("organization-mismatch", context),
  "secret-unreadable": () => ({
    kind: "secret-unreadable",
    message: "저장한 키를 읽을 수 없어요(암호화 키 목록이 바뀌었을 수 있어요). 같은 키를 다시 붙여넣으면 살아나요.",
  }),
  conflict: () => ({
    kind: "conflict",
    message: "같은 변경이 동시에 겹쳤어요. 목록을 다시 불러왔어요 — 결과를 확인해 주세요.",
  }),
} satisfies Record<CredentialRule, (error: ApiError, context: FailureContext) => CredentialFailure>;

export function classifyCredentialFailure(error: unknown, context: FailureContext = {}): CredentialFailure {
  // 응답이 없다. 키를 싣는 요청은 오프라인에서 일시정지하지 않고 바로 실패하므로, 연결이 끊긴 상태면 보내지 않은 것이다. 연결이
  // 살아 있는데 응답이 없으면 서버가 받아 처리한 뒤 끊겼을 수 있다.
  if (!isApiError(error) || error.status === 0) {
    return isOffline() ? { kind: "offline", message: OFFLINE_FAILURE_TEXT } : unknownOutcome();
  }
  if (error.status === 429 && apiErrorCode(error) === CHECK_LIMIT_CODE) {
    const seconds = detailNumber(error, "retryAfterSeconds") ?? CHECK_COOLDOWN_SECONDS;
    return {
      kind: "rate-limited",
      retryAfterSeconds: seconds,
      message: `확인 호출은 항목마다 1분에 한 번이에요. ${seconds}초 뒤 다시 해 주세요.`,
    };
  }
  if (error.status === 404) return { kind: "not-found", message: "이 항목은 이미 지워졌어요. 목록을 다시 불러왔어요." };
  if (error.status === 422 && error.fields !== undefined) {
    return { kind: "fields", fields: Object.keys(error.fields).filter(isFormField), message: FIELDS_FAILURE_TEXT };
  }
  const rule = detailString(error, "rule");
  if (rule !== undefined && isCredentialRule(rule)) return RULE_FAILURES[rule](error, context);
  // 거절 규칙이 없는 서버 오류는 커밋 뒤에 났을 수 있다(알림·감사 기록 단계 등).
  if (error.status >= 500) return unknownOutcome();
  return { kind: "other", message: serverMessage(error) ?? GENERIC_FAILURE_TEXT };
}

/** 화면이 본 목록이 틀렸다는 뜻의 실패 — 저장소 설정이 사라졌거나, 판이 낡았거나, 미리 계산한 켜기 막힘이 낡았거나, 항목이 없거나,
 * 같은 변경이 겹쳤거나, 결과를 받지 못했다. 다시 받아야 새 상태(저장소 띠·새 판·새 막힘·실제로 된 변경)가 보인다. */
export function failureReloadsList(failure: CredentialFailure): boolean {
  switch (failure.kind) {
    case "store-missing":
    case "stale-order":
    case "enable-blocked":
    case "not-found":
    case "conflict":
    case "unknown-outcome":
      return true;
    case "secret-rejected":
    case "upstream-unavailable":
    case "pool-uncovered":
    case "secret-unreadable":
    case "rate-limited":
    case "fields":
    case "offline":
    case "other":
      return false;
    default:
      return assertNever(failure);
  }
}

function unknownOutcome(): CredentialFailure {
  return { kind: "unknown-outcome", message: UNKNOWN_OUTCOME_TEXT };
}

function enableBlocked(blocker: EnableBlocker, context: FailureContext): CredentialFailure {
  return { kind: "enable-blocked", blocker, message: enableBlockerText(blocker, context.credentialState ?? "disabled") };
}

function isCredentialRule(value: string): value is CredentialRule {
  return Object.hasOwn(RULE_FAILURES, value);
}

function isRejectedReason(value: string): value is RejectedReason {
  return Object.hasOwn(REJECTED_REASON_TEXTS, value);
}

function isFormField(value: string): value is CredentialFormField {
  return value === "label" || value === "apiKey" || value === "creditUsd" || value === "alertPct";
}

function isOffline(): boolean {
  return typeof navigator !== "undefined" && !navigator.onLine;
}

function detailValue(error: ApiError, key: string): unknown {
  return typeof error.detail === "object" ? error.detail[key] : undefined;
}

function detailString(error: ApiError, key: string): string | undefined {
  const value = detailValue(error, key);
  return typeof value === "string" ? value : undefined;
}

function detailNumber(error: ApiError, key: string): number | undefined {
  const value = detailValue(error, key);
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function detailAxes(error: ApiError): ClaudeModelAxis[] {
  const value = detailValue(error, "axes");
  return Array.isArray(value) ? value.filter(isClaudeModelAxis) : [];
}

/** 서버의 거절 문장(이미 한국어). 모르는 거절일 때만 그대로 보인다. */
function serverMessage(error: ApiError): string | undefined {
  return detailString(error, "message") ?? (typeof error.detail === "string" ? error.detail : undefined);
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 실패: ${JSON.stringify(value)}`);
}
