import { API_BASE_URL } from "./client";

/**
 * 페이지가 숨거나 닫히는 순간에도 끝까지 보내야 하는 작은 쓰기(읽은 위치 저장 등)용. 브라우저는 보통 떠나는 페이지의
 * 요청을 끊지만 `keepalive` 가 붙은 fetch 는 페이지보다 오래 살려 보낸다 — axios(XHR)에는 그 옵션이 없어
 * `apiClient` 를 우회한다(SSE 가 `fetch` 를 직접 쓰는 것과 같은 이유). 그래서 `apiClient` 의 쿠키 첨부를
 * `credentials: "include"` 로, 기본 주소를 같은 `API_BASE_URL` 로 맞춘다. 브라우저는 keepalive 본문을 64KB 로
 * 제한하므로 큰 본문에는 쓰지 않는다.
 *
 * 최선 노력이다: 응답을 기다릴 화면이 이미 없을 수 있어 실패(네트워크·상태 코드)를 알리지 않고 삼킨다. 반환된
 * Promise 는 거부되지 않는다.
 */
export async function keepaliveFetch(method: "POST" | "PUT", path: string, body: unknown): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}${path}`, {
      method,
      keepalive: true,
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // 보내지 못한 위치는 다음 저장(디바운스 PUT)이 다시 덮는다.
  }
}
