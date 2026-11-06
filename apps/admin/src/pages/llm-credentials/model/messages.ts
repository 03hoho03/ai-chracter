import { CLAUDE_MODEL_AXES } from "./axes";
import type {
  AdminLlmCredential,
  AdminLlmCredentialCheckResponse,
  AdminLlmCredentialListResponse,
  ClaudeModelAxis,
  CredentialState,
} from "./credential";
import { ENV_ROUTE_CAUSE_LABELS } from "./labels";
import { formatUsd } from "./money";
import { candidateShift, firstCandidates, latestCheck, type CandidateChange, type EffectiveRoute } from "./status";

/** 성공 알림 한 건. 여러 문장은 설명 줄로 나눈다. */
export type NoticeCopy = { title: string; description?: string };

/** 같은 첫 후보 이동끼리 묶은 줄 — "Opus·Sonnet: 계정 A → 계정 B". 축 순서를 지킨다. */
export type CandidateChangeGroup = {
  axes: ClaudeModelAxis[];
  from: AdminLlmCredential | undefined;
  to: AdminLlmCredential | undefined;
};

/** 첫 후보가 바뀌면 그 계정으로 나가는 첫 요청이 프롬프트 캐시를 새로 쓴다. */
export const CACHE_BREAK_TEXT =
  "다음 호출부터 바뀐 항목의 계정으로 나가요. 진행 중인 방은 프롬프트 캐시가 한 번 끊겨 그 다음 턴 입력 비용이 한 번 커져요.";

/** 같은 지문의 키를 다시 붙여넣었다. 옛 키가 곧 지금 키라 폐기할 것도 다시 확인할 것도 없어 이 한 문장만 둔다. */
export const SAME_KEY_REPLACED_TEXT = "같은 키 — 암호문만 다시 썼어요, 확인 기록은 그대로예요.";

/** 지운 항목의 키를 콘솔에서 폐기해도 되는가. env 롤백 키와 같은 키면 되돌리기 경로가 그 키를 쓴다. */
export function deletedKeyText(sameAsEnvKey: boolean): string {
  return sameAsEnvKey
    ? "이 키는 env 롤백 키와 같아요 — Anthropic 콘솔에서 폐기하지 마세요. env 되돌리기 경로가 같은 키를 써요."
    : "이 키를 더 쓰지 않으면 Anthropic 콘솔에서도 폐기하세요.";
}

/** 키를 바꾼 뒤 옛 키를 콘솔에서 폐기해도 되는가 — 교체 전 항목이 env 롤백 키와 같은 키였는지로 갈린다. */
export function replacedKeyText(oldWasEnvKey: boolean): string {
  return oldWasEnvKey
    ? "옛 키는 env 롤백 키와 같아요 — 콘솔에서 폐기하지 마세요."
    : "옛 키를 더 쓰지 않으면 콘솔에서 폐기하세요.";
}

export function groupCandidateChanges(changes: readonly CandidateChange[]): CandidateChangeGroup[] {
  const groups: CandidateChangeGroup[] = [];
  for (const change of changes) {
    const group = groups.find((entry) => entry.from?.id === change.from?.id && entry.to?.id === change.to?.id);
    if (group === undefined) groups.push({ axes: [change.axis], from: change.from, to: change.to });
    else group.axes.push(change.axis);
  }
  return groups;
}

export function addedNotice(credential: AdminLlmCredential, displayPosition: number): NoticeCopy {
  const notes = ["확인 호출 → 켜기 순서로 진행하세요."];
  if (!credential.organizationVerified) {
    notes.push("조직 헤더가 없어 조직 미확인으로 저장했어요. 확인 호출이 다시 대조해요.");
  }
  if (credential.sameAsEnvKey) {
    notes.push("env 롤백 키와 같은 키예요 — 지우거나 교체해도 콘솔에서 폐기하지 마세요.");
  }
  return {
    title: `‘${credential.label}’을(를) 추가했어요 — 꺼진 채 ${displayPosition}번째에 들어갔어요.`,
    description: notes.join(" "),
  };
}

/** 키 교체 결과. 같은 키인지는 교체 전 지문(대화상자를 연 순간의 값)과 응답 지문으로 가린다 — 응답 뒤의 캐시는 이미 새 값이다.
 * 다른 키인데 응답 확인 기록에 런타임 기준 행이 있으면 예전에 이 항목에서 쓰던 키라 그 키로 한 확인이 다시 센다. */
export function secretReplacedNotice(
  before: Pick<AdminLlmCredential, "label" | "secretFingerprint" | "sameAsEnvKey">,
  after: AdminLlmCredential,
): NoticeCopy {
  if (after.secretFingerprint === before.secretFingerprint) return { title: SAME_KEY_REPLACED_TEXT };
  const isReturningKey = after.checks.some((check) => check.isRuntimeBasis);
  return {
    title: isReturningKey
      ? `‘${after.label}’의 키를 바꿨어요. 예전에 쓰던 키라 그 키로 한 이전 확인이 다시 세요.`
      : `‘${after.label}’의 키를 바꿨어요. 확인 호출이 통과할 때까지 이 항목을 쓰지 않아요.`,
    description: replacedKeyText(before.sameAsEnvKey),
  };
}

export function editedNotice(isChanged: boolean): NoticeCopy {
  return { title: isChanged ? "저장했어요." : "바뀐 것이 없어요." };
}

export function creditBasisNotice(credential: AdminLlmCredential): NoticeCopy {
  return credential.creditUsd === null
    ? { title: "충전액을 지웠어요 — 사용액을 세지 않아요." }
    : { title: `충전액 ${formatUsd(credential.creditUsd)} 기준으로 지금부터 다시 세요.` };
}

export function deletedNotice(credential: Pick<AdminLlmCredential, "label" | "sameAsEnvKey">): NoticeCopy {
  return { title: `‘${credential.label}’을(를) 지웠어요.`, description: deletedKeyText(credential.sameAsEnvKey) };
}

export function reorderedNotice(list: AdminLlmCredentialListResponse): NoticeCopy {
  return { title: `순서를 저장했어요: ${list.credentials.map((credential) => credential.label).join(" → ")}` };
}

/** 켜기·끄기 응답(바뀐 뒤의 항목)과 바꾸기 전 상태로 쓴다. 응답만으로는 꺼짐에서 켰는지 소진에서 다시 켰는지 모르므로 부르는 쪽이
 * 누른 순간의 상태를 넘긴다 — 소진에서 켠 것은 버튼 글자처럼 "다시 켰어요"다. */
export function stateChangedNotice(credential: AdminLlmCredential, stateBefore: CredentialState): NoticeCopy {
  if (credential.state !== "active") return { title: `‘${credential.label}’을(를) 껐어요.` };
  return { title: `‘${credential.label}’을(를) ${stateBefore === "exhausted" ? "다시 켰어요" : "켰어요"}.` };
}

/** 확인 호출 한 회차의 요약. 첫 후보에서 빠진 축은 알림이 아니라 그 항목의 확인 블록이 진다. */
export function checkedNotice(response: AdminLlmCredentialCheckResponse): NoticeCopy {
  const { credential, calls } = response;
  const latest = latestCheck(credential.checks);
  const rows = latest === undefined ? [] : credential.checks.filter((check) => check.run === latest.run);
  const passed = rows.filter((check) => check.passed).length;
  const transient = rows.filter((check) => check.errorKind === "unavailable").length;
  const canEnableNow = credential.state !== "active" && credential.enableBlocker === null;
  return {
    title: `확인 호출 끝 — 모델 ${calls}개 · 통과 ${passed}축 · 일시 오류 ${transient}축`,
    description: canEnableNow ? "이제 켤 수 있어요." : undefined,
  };
}

/** 확인 호출로 이 항목이 첫 후보에서 빠진 축 — 확정 실패한 모델만 빠진다(일시 오류는 런타임이 이전 결과로 내려가 그대로 받는다). 목록이
 * 실제로 쓰이는 동안만 알릴 결과가 있다. */
export function droppedByCheck(
  before: AdminLlmCredentialListResponse,
  checked: AdminLlmCredential,
  route: EffectiveRoute,
): CandidateChange[] {
  if (route.kind !== "list") return [];
  const after = before.credentials.map((credential) => (credential.id === checked.id ? checked : credential));
  return candidateShift(before.credentials, after).filter((change) => change.from?.id === checked.id);
}

/** 목록 사용 켜기·끄기 확인에 보일 것. 어드민 설정만 보면 서버 스위치가 꺼진 동안 "다음 호출부터 목록"이 거짓이 되므로, 지금과 바꾼
 * 뒤의 실효 경로를 견줘 문장을 고른다. */
export type PoolChangePreview = {
  sentences: string[];
  changes: CandidateChange[];
  /** 바뀌는 쪽이 env 키다 — 켤 때는 "env 키 → 항목", 끌 때는 "항목 → env 키"로 읽는다. */
  across: "from-env" | "to-env" | undefined;
  showCacheNote: boolean;
};

export function poolChangePreview(
  enabled: boolean,
  list: AdminLlmCredentialListResponse,
  now: EffectiveRoute,
  after: EffectiveRoute,
): PoolChangePreview {
  if (now.kind === "env" && now.cause === "switch-off") {
    return {
      sentences: ["서버 스위치가 꺼져 있어 지금 호출은 바뀌지 않아요. 서버 스위치가 켜지면 이 설정을 따라요."],
      changes: [],
      across: undefined,
      showCacheNote: false,
    };
  }
  if (enabled) {
    if (after.kind === "list") {
      return {
        sentences: [
          "다음 호출부터 Claude 호출이 이 목록으로 나가요 — 모델마다 아래 항목이 받아요. 받을 항목이 없는 모델은 env 키로 넘어가지 않고 실패·환불돼요.",
        ],
        changes: acrossEnvChanges(list.credentials, "from-env"),
        across: "from-env",
        showCacheNote: true,
      };
    }
    return {
      sentences: [
        after.kind === "unknown"
          ? "서버 스위치 값을 읽지 못해 켠 뒤의 호출 경로를 단정할 수 없어요. 서버 스위치가 켜져 있으면 다음 호출부터 이 목록으로 나가요."
          : afterEnvSentence(after),
      ],
      changes: [],
      across: undefined,
      showCacheNote: false,
    };
  }
  if (now.kind === "list") {
    return {
      sentences: ["다음 호출부터 Claude 호출이 env 키로 나가요. 목록 순서와 항목은 그대로 남아요."],
      changes: acrossEnvChanges(list.credentials, "to-env"),
      across: "to-env",
      showCacheNote: true,
    };
  }
  return {
    sentences: [
      now.kind === "unknown"
        ? "서버 스위치 값을 읽지 못했어요. 목록이 쓰이고 있었다면 다음 호출부터 env 키로 나가요."
        : "지금 호출은 이미 env 키라 바뀌지 않아요. 목록 순서와 항목은 그대로 남아요.",
    ],
    changes: [],
    across: undefined,
    showCacheNote: false,
  };
}

export function poolChangedNotice(enabled: boolean, after: EffectiveRoute): NoticeCopy {
  if (!enabled) return { title: "목록 사용을 껐어요 — 다음 호출부터 env 키로 나가요." };
  if (after.kind === "list") return { title: "목록 사용을 켰어요 — 다음 호출부터 이 목록으로 나가요." };
  return { title: "목록 사용을 켰어요.", description: afterEnvSentence(after) };
}

/** 한쪽이 env 키인 전환(목록 사용 켜기·끄기)에서 바뀌는 축 — 네 축 모두다. 전후 첫 후보를 견주는 `candidateShift` 로는 목록에서 받을
 * 항목이 없는 축이 전후 모두 "없음"이라 빠지는데, 그 축도 실제로는 끄면 "없음(실패·환불) → env 키", 켜면 "env 키 → 없음"으로 바뀐다. */
function acrossEnvChanges(
  credentials: readonly AdminLlmCredential[],
  across: NonNullable<PoolChangePreview["across"]>,
): CandidateChange[] {
  const firsts = firstCandidates(credentials);
  return CLAUDE_MODEL_AXES.map((axis) =>
    across === "from-env" ? { axis, from: undefined, to: firsts[axis] } : { axis, from: firsts[axis], to: undefined },
  );
}

/** 켜도 목록이 실제로 쓰이지 않는 이유. */
function afterEnvSentence(route: Exclude<EffectiveRoute, { kind: "list" }>): string {
  if (route.kind === "unknown") return "서버 스위치 값을 읽지 못해 지금 호출 경로를 단정할 수 없어요.";
  if (route.cause === "empty") return "목록이 비어 있어 켜도 지금 호출은 그대로 env 키예요.";
  return `${ENV_ROUTE_CAUSE_LABELS[route.cause]} 켜도 지금 호출은 그대로 env 키예요.`;
}
