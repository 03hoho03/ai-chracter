/**
 * 백엔드 API 호출 결과 세 갈래.
 *
 * `notFound`(404)와 `unavailable`(5xx·타임아웃·네트워크 오류·응답 형식 파손)을 **반드시**
 * 구분한다 — API 장애를 "이 페이지 없음"으로 번역하면 검색엔진이 장애 중에 페이지를
 * 색인에서 지우고, 크롤러는 공유 미리보기를 "이미지 없음"으로 굳혀 버린다.
 */
export type ApiResult =
  | { kind: "ok"; data: unknown }
  | { kind: "notFound" }
  | { kind: "unavailable" };

/**
 * 봇 응답 하나를 만드는 데 허용하는 API 대기 시간. 크롤러는 오래 기다려 주지 않고,
 * 여기서 막히면 그 응답 전체가 막힌다.
 */
const API_TIMEOUT_MS = 3000;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * `GET {API_BASE_URL}{path}`의 JSON을 받아 온다. 던지지 않고 항상 `ApiResult`로 돌려준다.
 *
 * `API_BASE_URL`이 `https://host/api`처럼 경로 프리픽스를 가질 수 있으므로 `new URL()`이
 * 아니라 문자열 결합으로 붙인다(`new URL("/contents", base)`는 프리픽스를 날린다).
 */
export async function fetchApiJson(
  apiBaseUrl: string,
  path: string,
): Promise<ApiResult> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl.replace(/\/+$/, "")}${path}`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch (error) {
    console.warn(`[worker] GET ${path} 요청이 실패했다`, error);
    return { kind: "unavailable" };
  }

  if (response.status === 404) return { kind: "notFound" };
  if (!response.ok) {
    console.warn(`[worker] GET ${path} → ${response.status}`);
    return { kind: "unavailable" };
  }

  try {
    return { kind: "ok", data: await response.json() };
  } catch (error) {
    console.warn(`[worker] GET ${path} 응답을 JSON으로 읽지 못했다`, error);
    return { kind: "unavailable" };
  }
}
