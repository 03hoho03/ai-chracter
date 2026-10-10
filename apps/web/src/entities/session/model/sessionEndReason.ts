import { isSessionLostError } from "./sessionLost";
import { isSuspendedError } from "./suspendedAccount";

/** 요청이 세션이 끝나서 거절됐을 때 그 까닭. 둘 다 `resetSessionIfLost` 가 세션을 비우는 실패지만 사용자가 할 일이 다르다 —
 * 로그인이 풀린 것은 다시 로그인하면 되고, 정지는 다시 로그인해도 풀리지 않는다. */
export type SessionEndReason = "sessionLost" | "suspended";

/** 전송 화면이 "실패했다" 대신 까닭에 맞는 안내를 고르게 한다. 세션과 무관한 실패면 `undefined`. */
export function getSessionEndReason(error: unknown): SessionEndReason | undefined {
  if (isSessionLostError(error)) return "sessionLost";
  if (isSuspendedError(error)) return "suspended";
  return undefined;
}
