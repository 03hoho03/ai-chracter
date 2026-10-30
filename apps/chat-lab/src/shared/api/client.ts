import axios from "axios";

import { assertNever } from "@/shared/lib/assertNever";

import type { components } from "./generated";
import { findStaticTurn, isStaticMode, StaticBundleError, staticBundleState } from "./staticBundle";

/** 측정 서버(`apps/api/scripts/chat_lab_server.py`)의 기본 주소 — 서버의 기본 포트와 같다. */
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8791";

export const CHAT_LAB_API_BASE_URL = import.meta.env.VITE_CHAT_LAB_API ?? DEFAULT_API_BASE_URL;

type Schemas = components["schemas"];
type Health = Schemas["Health"];
type RunList = Schemas["RunList"];
/** 런 목록의 한 줄. 화면의 목록·미리보기 계산이 이 모양을 받는다. */
export type RunListItem = Schemas["RunListItem"];
// 런 상세 화면의 계산(턴 목록 행·토큰 막대·검사기)이 받는 모양.
export type RunDetail = Schemas["RunDetail"];
export type TurnSummary = Schemas["TurnSummary"];
export type StatSeries = Schemas["StatSeries"];
export type TimelineMarker = Schemas["TimelineMarker"];
export type Mismatch = Schemas["Mismatch"];
export type Caution = Schemas["Caution"];
export type TurnDetail = Schemas["TurnDetail"];
export type AttemptDetail = Schemas["AttemptDetail"];
export type CallCostView = Schemas["CallCostView"];
export type RunMetrics = Schemas["RunMetrics"];
export type TurnMetrics = Schemas["TurnMetrics"];
export type ReplyFlagsView = Schemas["ReplyFlagsView"];
export type DriverStatChange = Schemas["DriverStatChange"];
export type RecordLimit = Schemas["RecordLimit"];
export type RunBundle = Schemas["RunBundle"];
type ExportTurnsRequest = Schemas["ExportTurnsRequest"];
type ExportTurnsResult = Schemas["ExportTurnsResult"];

/**
 * 측정 서버 호출은 아래 엔드포인트 함수를 거쳐 이 인스턴스로만 나간다.
 *
 * `Content-Type` 을 기본 헤더로 못 박는 것은 측정 서버가 JSON 이 아닌 쓰기 요청을 라우팅 전에 415 로 끊어서다. 본문이 없는
 * 요청(GET)에서는 axios 가 이 헤더를 빼고 보낸다.
 *
 * 응답 본문은 axios 제네릭으로 생성 타입을 붙일 뿐 실행 중에 검사하지 않는다. 측정 서버가 응답을 핸들러 반환 타입의 모델로
 * 직렬화하고 그 모델에서 `openapi.json` 과 `generated.ts` 가 차례로 나오며, 두 생성물이 서버와 어긋나지 않는지는 CI 가 본다.
 */
const chatLabClient = axios.create({
  baseURL: CHAT_LAB_API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// 정적 HTML 로 연 화면은 측정 서버에 요청하지 않는다 — 데이터는 모두 파일 안에 있어서, 요청이 나간다는 것은 서버가 있어야 하는
// 동작을 숨기다 빠뜨린 자리다. 그 요청은 파일을 연 컴퓨터의 127.0.0.1 로 나가고, `file://` 의 Origin(`null`)은 측정 서버 CORS
// 가 받지 않아 응답을 읽지 못한 채 "측정 서버에 닿지 못했다 — 띄운다" 안내로 끝난다. 정적 파일에서는 틀린 안내라, 요청이 나가기
// 전에 여기서 정적 화면의 실패로 막는다.
chatLabClient.interceptors.request.use((config) => {
  if (isStaticMode()) throw new StaticBundleError("serverless", "정적 HTML 로 연 화면은 측정 서버에 닿지 않는다");
  return config;
});

/** 런 id 는 base64url 이라 지금은 인코딩해도 그대로지만, 경로 한 마디에 넣는 값이라 인코딩을 거친다. */
function runPath(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}`;
}

export async function getHealth(): Promise<Health> {
  const response = await chatLabClient.get<Health>("/health");
  return response.data;
}

/** 런 목록. `refresh` 이면 서버가 런 루트를 다시 훑는다(실데이터에서 수십 초). */
export async function getRuns(params: { refresh?: boolean } = {}): Promise<RunList> {
  const response = await chatLabClient.get<RunList>("/runs", { params });
  return response.data;
}

/**
 * 정적 HTML 로 열었으면 그 파일에 실린 묶음, 측정 서버를 읽는 화면이면 undefined. 상세·지표·턴은 이 값이 있으면 서버 대신 여기서
 * 읽는다 — 서버가 낸 응답을 그대로 실은 것이라 결합·지표를 다시 계산하지 않는다. 읽지 못한 파일이거나 이 파일의 런이 아니면 던진다.
 */
function staticRun(runId: string): RunBundle | undefined {
  const state = staticBundleState();
  switch (state.kind) {
    case "absent":
      return undefined;
    case "broken":
      throw new StaticBundleError("broken", state.reason);
    case "ready":
      if (state.bundle.detail.run.runId !== runId) {
        throw new StaticBundleError("notFound", "이 파일에는 그 런이 없다 — 정적 HTML 하나에는 런 하나만 실린다");
      }
      return state.bundle;
    default:
      return assertNever(state);
  }
}

export async function getRun(runId: string): Promise<RunDetail> {
  const bundle = staticRun(runId);
  if (bundle !== undefined) return bundle.detail;
  const response = await chatLabClient.get<RunDetail>(runPath(runId));
  return response.data;
}

export async function getTurn(runId: string, clientTurn: number): Promise<TurnDetail> {
  const bundle = staticRun(runId);
  if (bundle !== undefined) {
    const detail = findStaticTurn(bundle, clientTurn);
    if (detail === undefined) throw new StaticBundleError("notFound", `이 파일에 턴 ${clientTurn} 이 없다`);
    return detail;
  }
  const response = await chatLabClient.get<TurnDetail>(`${runPath(runId)}/turns/${clientTurn}`);
  return response.data;
}

export async function getRunMetrics(runId: string): Promise<RunMetrics> {
  const bundle = staticRun(runId);
  if (bundle !== undefined) return bundle.metrics;
  const response = await chatLabClient.get<RunMetrics>(`${runPath(runId)}/metrics`);
  return response.data;
}

/** 정적 HTML 로 굳힐 통째 응답. `raw` 가 거짓이면 서버가 프롬프트·지시문·기억 스냅숏 본문을 빼고 준다. */
export async function getRunBundle(runId: string, params: { raw: boolean }): Promise<RunBundle> {
  const response = await chatLabClient.get<RunBundle>(`${runPath(runId)}/bundle`, { params });
  return response.data;
}

/** 로컬 DB 에서 이 런 방의 턴 기록을 런의 묶음 폴더에 파일로 쓰게 한다. 파일이 이미 있으면 `force` 일 때만 다시 쓴다. */
export async function exportTurns(runId: string, body: ExportTurnsRequest): Promise<ExportTurnsResult> {
  const response = await chatLabClient.post<ExportTurnsResult>(`${runPath(runId)}/export-turns`, body);
  return response.data;
}
