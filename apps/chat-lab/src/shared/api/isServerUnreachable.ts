import { isAxiosError } from "axios";

/**
 * 측정 서버에 닿지 못해 응답 자체가 없는 실패인가 — 서버가 꺼졌거나, 다른 주소에 떠 있거나, 다른 오리진이라 CORS 가 막았다.
 * 이때 화면은 서버의 거부 사유 대신 서버를 띄우는 방법을 보여 준다. 응답이 있는 실패(4xx·5xx)는 `readLabError` 가 다룬다.
 */
export function isServerUnreachable(error: unknown): boolean {
  return isAxiosError(error) && error.response === undefined;
}
