import type { components } from "./generated";
import { STATIC_BUNDLE_ELEMENT_ID } from "./staticBundleElement";

// 타입을 `client.ts` 가 아니라 생성 타입에서 바로 받는다 — `client.ts` 가 이 파일을 불러 쓰므로 서로 부르지 않게 한다.
type RunBundle = components["schemas"]["RunBundle"];
type TurnDetail = components["schemas"]["TurnDetail"];

/**
 * 정적 HTML 에 실린 런 묶음(측정 서버의 통째 응답 그대로).
 * - `absent`: 실린 태그가 없다 — 측정 서버를 읽는 화면이다.
 * - `ready`: 이 파일의 런 하나. 상세·지표·턴 상세를 모두 여기서 읽고 측정 서버에는 닿지 않는다.
 * - `broken`: 태그는 있는데 읽지 못했다. 없음으로 치면 측정 서버를 읽는 화면으로 넘어가, 파일이 깨졌다는 까닭 대신 "측정 서버에
 *   닿지 못했다 — 띄운다"는 틀린 안내가 뜬다(`file://` 의 요청은 측정 서버 CORS 가 받지 않는다). 그래서 따로 둔다.
 */
export type StaticBundleState =
  | { kind: "absent" }
  | { kind: "ready"; bundle: RunBundle }
  | { kind: "broken"; reason: string };

/**
 * 태그 글을 읽는다. 겉모양(`raw`·`detail.run.runId`·`metrics`·`turns`)만 본다 — 글은 측정 서버가 낸 응답을 내보내기 스크립트가
 * 그대로 실은 것이고, 서버 응답을 실행 중에 검사하지 않는 것과 같다(`client.ts`). 겉모양 검사는 엉뚱한 본문(측정 서버의 거부
 * 본문 등)을 실은 파일을 걸러 낸다.
 */
export function parseStaticBundle(text: string | null | undefined): StaticBundleState {
  if (text === null || text === undefined) return { kind: "absent" };
  if (text.trim() === "") return { kind: "broken", reason: "이 파일에 실린 런 데이터가 비어 있다" };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { kind: "broken", reason: `이 파일에 실린 런 데이터가 JSON 으로 읽히지 않는다: ${String(error)}` };
  }
  if (!isRunBundle(value)) return { kind: "broken", reason: "이 파일에 실린 데이터가 런 묶음 꼴이 아니다" };
  return { kind: "ready", bundle: value };
}

/** 턴 번호(배열 순번이 아니다)로 그 턴 상세. 이 파일에 없는 턴이면 undefined. */
export function findStaticTurn(bundle: RunBundle, turn: number): TurnDetail | undefined {
  return bundle.turns.find((detail) => detail.turn === turn);
}

let readState: StaticBundleState | undefined;

/** 이 문서에 실린 묶음. 문서는 열린 뒤 바뀌지 않으므로 처음 한 번만 읽는다. */
export function staticBundleState(): StaticBundleState {
  readState ??= parseStaticBundle(document.getElementById(STATIC_BUNDLE_ELEMENT_ID)?.textContent);
  return readState;
}

/**
 * 정적 HTML 로 연 화면에서 런·턴을 내지 못한 까닭. 화면은 측정 서버의 거부(`readLabError`)와 따로 이것을 보고 "다시 시도"·"런
 * 목록으로" 없이 문장만 보인다 — 파일은 다시 읽어도 같고, 목록은 이 파일에 없다.
 * - `broken`: 실린 데이터를 읽지 못했다.
 * - `notFound`: 이 파일의 런이 아니거나 이 파일에 없는 턴이다.
 * - `serverless`: 측정 서버가 있어야 하는 요청이다(목록·턴 기록 내보내기 등) — 정적 파일은 측정 서버에 닿지 않는다.
 */
export class StaticBundleError extends Error {
  readonly reason: "broken" | "notFound" | "serverless";

  constructor(reason: StaticBundleError["reason"], message: string) {
    super(message);
    this.name = "StaticBundleError";
    this.reason = reason;
  }
}

/** 정적 HTML 로 연 화면인가 — 실린 묶음을 읽지 못했어도 정적이다(측정 서버로 넘어가지 않는다). */
export function isStaticMode(): boolean {
  return staticBundleState().kind !== "absent";
}

function isRunBundle(value: unknown): value is RunBundle {
  return (
    isObject(value) &&
    typeof value.raw === "boolean" &&
    isObject(value.detail) &&
    isObject(value.detail.run) &&
    typeof value.detail.run.runId === "string" &&
    isObject(value.metrics) &&
    Array.isArray(value.turns)
  );
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
