import { CLAUDE_MODEL_AXES } from "./axes";
import type {
  AdminLlmCredential,
  AdminLlmCredentialCheckItem,
  AdminLlmCredentialListResponse,
  ClaudeModelAxis,
  CredentialState,
  CredentialStateReason,
} from "./credential";

const NO_AXES: ReadonlySet<ClaudeModelAxis> = new Set();

/**
 * 이 항목이 지금 받을 수 있는 축. 축 자체는 서버가 런타임과 같은 함수로 계산해 싣는 `runtimeAxes` 이고, 이 함수는 그 칸에 들어
 * 있지 않은 조건(켜짐·조직 확인·공급자·허용 목록)만 더한다 — 확인 기록으로 축을 다시 고르지 않는다(조직 신호를 정하는 기록은 응답의
 * 확인 행에 실리지 않을 수 있어 다시 계산하면 런타임과 다른 답이 난다). 허용 목록은 응답에 없어, 목록에서 빠진 조직이면 서버가 켜기
 * 막힘으로 알려 주는 값으로 대신 본다 — 조직이 확인된 항목에서 서버가 그 값을 내는 것은 허용 목록 밖일 때뿐이다.
 */
export function servableAxes(credential: AdminLlmCredential): ReadonlySet<ClaudeModelAxis> {
  const isEligible =
    credential.provider === "anthropic" &&
    credential.state === "active" &&
    credential.organizationVerified &&
    credential.enableBlocker !== "account-not-allowed";
  return isEligible ? new Set(credential.runtimeAxes) : NO_AXES;
}

export type EnvRouteCause = "switch-off" | "pool-off" | "store-missing" | "notifications-missing" | "empty";

export type EffectiveRoute = { kind: "list" } | { kind: "env"; cause: EnvRouteCause } | { kind: "unknown" };

/**
 * 지금 호출이 실제로 어디로 나가는가. 서버 런타임의 조건(서버 스위치 ∧ 어드민 목록 사용 ∧ 행 1개 이상)에 기동 검증이 보장하는 두
 * 설정(저장소·알림)을 함께 본다 — 두 응답이 다른 프로세스에서 왔거나 스위치 조회가 낡았을 때 "사용 중"을 잘못 그리지 않게. 서버
 * 스위치를 아직 못 읽었으면(대기·실패·그 칸이 없는 옛 서버) 단정하지 않는다. "사용 중" 표지·목록 사용 절·확인 대화상자를 띄울지가
 * 모두 이 값 하나를 따른다.
 */
export function effectiveRoute(list: AdminLlmCredentialListResponse, runtimeSwitch: boolean | undefined): EffectiveRoute {
  if (runtimeSwitch === undefined) return { kind: "unknown" };
  if (!runtimeSwitch) return { kind: "env", cause: "switch-off" };
  if (!list.poolEnabled) return { kind: "env", cause: "pool-off" };
  if (!list.storeConfigured) return { kind: "env", cause: "store-missing" };
  if (!list.notificationsConfigured) return { kind: "env", cause: "notifications-missing" };
  if (list.credentials.length === 0) return { kind: "env", cause: "empty" };
  return { kind: "list" };
}

export type FirstCandidates = Record<ClaudeModelAxis, AdminLlmCredential | undefined>;

/** 축마다 배열 순서로 첫 번째로 받을 수 있는 항목. 배열 순서가 곧 목록 순서다(동작을 흉내 낸 배열은 `position` 칸을 고치지 않는다).
 * 실효 경로와 무관하게 계산한다 — 목록을 쓰면 누가 받는가. */
export function firstCandidates(credentials: readonly AdminLlmCredential[]): FirstCandidates {
  const servable = credentials.map((credential) => ({ credential, axes: servableAxes(credential) }));
  const firstFor = (axis: ClaudeModelAxis) => servable.find((entry) => entry.axes.has(axis))?.credential;
  return { opus: firstFor("opus"), sonnet: firstFor("sonnet"), haiku_writer: firstFor("haiku_writer"), haiku: firstFor("haiku") };
}

/** 한 축의 첫 후보가 바뀐 것. `to` 가 없으면 그 축을 받을 항목이 없어진다 — 목록이 실효인 동안 그 모델 호출은 실패·환불된다. */
export type CandidateChange = {
  axis: ClaudeModelAxis;
  from: AdminLlmCredential | undefined;
  to: AdminLlmCredential | undefined;
};

/** 동작 전후의 첫 후보를 견줘 바뀐 축만 축 순서로. 확인 대화상자·확인 뒤 결과 안내가 이것만 읽는다. */
export function candidateShift(
  before: readonly AdminLlmCredential[],
  after: readonly AdminLlmCredential[],
): CandidateChange[] {
  const was = firstCandidates(before);
  const now = firstCandidates(after);
  return CLAUDE_MODEL_AXES.flatMap((axis) =>
    was[axis]?.id === now[axis]?.id ? [] : [{ axis, from: was[axis], to: now[axis] }],
  );
}

export type MoveDirection = "up" | "down";

/** 순서 동작을 흉내 낸 목록 — `index` 의 항목을 한 칸 옮긴다. 끝을 넘으면 그대로 돌려준다. */
export function moveCredential(
  credentials: readonly AdminLlmCredential[],
  index: number,
  direction: MoveDirection,
): AdminLlmCredential[] {
  const target = direction === "up" ? index - 1 : index + 1;
  const moving = credentials[index];
  const other = credentials[target];
  if (moving === undefined || other === undefined) return [...credentials];
  return credentials.map((credential, at) => {
    if (at === index) return other;
    if (at === target) return moving;
    return credential;
  });
}

/** 켜기·끄기를 흉내 낸 목록. 켜기는 켜기 조건이 통과한 항목만 누를 수 있으므로 그 확인 기록 그대로 상태만 바꾼다. `runtimeAxes` 는
 * 상태와 무관하게 계산된 값이라 꺼진·소진된 항목도 "켜면 받을 축"을 이미 갖는다. */
export function withCredentialState(
  credentials: readonly AdminLlmCredential[],
  id: string,
  state: CredentialState,
): AdminLlmCredential[] {
  return credentials.map((credential) => (credential.id === id ? { ...credential, state } : credential));
}

/** 삭제를 흉내 낸 목록. */
export function withoutCredential(credentials: readonly AdminLlmCredential[], id: string): AdminLlmCredential[] {
  return credentials.filter((credential) => credential.id !== id);
}

/** 항목 응답(확인 호출·수정 등)으로 그 항목만 바꿔 끼운 목록. */
export function withCredential(
  credentials: readonly AdminLlmCredential[],
  next: AdminLlmCredential,
): AdminLlmCredential[] {
  return credentials.map((credential) => (credential.id === next.id ? next : credential));
}

/** 다른 키로 교체하는 경우를 흉내 낸 목록 — 그 항목은 확인이 통과할 때까지 받을 축이 없다. 붙여넣을 키가 예전에 이 항목에서 쓰던
 * 키인지 화면은 모르므로 미리보기는 "다른 키면" 조건부이고, 실제 결과는 응답의 `runtimeAxes` 가 정한다. */
export function withRotatedSecret(credentials: readonly AdminLlmCredential[], id: string): AdminLlmCredential[] {
  return credentials.map((credential) => (credential.id === id ? { ...credential, runtimeAxes: [] } : credential));
}

/** 받을 수 있는 축이 없는 켜진 항목의 원인. 위에서부터 처음 걸리는 것이다. */
export type UnverifiedCause =
  | "provider-unsupported"
  | "organization-unverified"
  | "account-not-allowed"
  | "organization-mismatch"
  | "no-servable-axis";

export type CredentialStatus =
  | { kind: "serving"; axes: ClaudeModelAxis[] }
  | { kind: "standby"; axes: ClaudeModelAxis[] }
  | { kind: "unverified"; cause: UnverifiedCause }
  | { kind: "exhausted"; reason: CredentialStateReason | null }
  | { kind: "disabled"; neverChecked: boolean };

/**
 * 항목 상태 표지. "사용 중"은 실효 경로가 목록이고 그 항목이 어느 축의 첫 후보일 때뿐이다 — 실효 경로가 env 키이거나 알 수 없으면
 * 아무 항목도 사용 중이 아니다(목록 사용 절의 경로 줄이 이유를 말한다). 축은 확인 행이 아니라 `servableAxes` 를 따른다.
 */
export function describeCredentialStatus(
  credential: AdminLlmCredential,
  firsts: FirstCandidates,
  route: EffectiveRoute,
): CredentialStatus {
  switch (credential.state) {
    case "disabled":
      return { kind: "disabled", neverChecked: credential.checks.length === 0 };
    case "exhausted":
      return { kind: "exhausted", reason: credential.stateReason };
    case "active": {
      const servable = servableAxes(credential);
      if (servable.size === 0) return { kind: "unverified", cause: unverifiedCause(credential) };
      const servingAxes =
        route.kind === "list" ? CLAUDE_MODEL_AXES.filter((axis) => firsts[axis]?.id === credential.id) : [];
      if (servingAxes.length > 0) return { kind: "serving", axes: servingAxes };
      return { kind: "standby", axes: CLAUDE_MODEL_AXES.filter((axis) => servable.has(axis)) };
    }
    default:
      return assertNever(credential.state);
  }
}

function unverifiedCause(credential: AdminLlmCredential): UnverifiedCause {
  if (credential.provider !== "anthropic") return "provider-unsupported";
  if (!credential.organizationVerified) return "organization-unverified";
  if (credential.enableBlocker === "account-not-allowed") return "account-not-allowed";
  if (credential.enableBlocker === "organization-mismatch") return "organization-mismatch";
  return "no-servable-axis";
}

/** 한 축의 확인 결과 — 최신 행과, 그것이 런타임 기준이 아닐 때 서버가 함께 싣는 기준 행. 표시용이다: 받을 수 있는 축은 확인 행이
 * 아니라 `runtimeAxes` 가 정한다(앞 행이 통과여도 풀리지 않은 조직 신호가 있으면 그 축은 빈다). */
export type AxisCheckRows = {
  axis: ClaudeModelAxis;
  latest: AdminLlmCredentialCheckItem;
  previous: AdminLlmCredentialCheckItem | undefined;
};

/** 축마다 행이 하나 또는 둘(서버가 축 순서로 최신 행, 그것이 기준이 아니면 기준 행을 하나 더 싣는다). 회차로 다시 정렬해 응답 행
 * 순서에 기대지 않는다. */
export function axisCheckRows(checks: readonly AdminLlmCredentialCheckItem[]): AxisCheckRows[] {
  return CLAUDE_MODEL_AXES.flatMap((axis) => {
    const [latest, previous] = checks.filter((check) => check.modelAxis === axis).sort((a, b) => b.run - a.run);
    return latest === undefined ? [] : [{ axis, latest, previous }];
  });
}

/** 회차가 가장 큰 확인 행 — "마지막 확인" 시각과 회차를 보인다. 한 회차는 언제나 네 축을 함께 쓴다. */
export function latestCheck(checks: readonly AdminLlmCredentialCheckItem[]): AdminLlmCredentialCheckItem | undefined {
  return checks.reduce<AdminLlmCredentialCheckItem | undefined>(
    (latest, check) => (latest === undefined || check.run > latest.run ? check : latest),
    undefined,
  );
}

function assertNever(value: never): never {
  throw new Error(`알 수 없는 상태: ${String(value)}`);
}
