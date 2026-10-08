/** 포트원 결제창·본인인증창 호출 한 번이 어떻게 끝났는지.
 *
 * - `returned` — SDK 가 값을 돌려줬다. 결제·인증 실패와 이용자 취소도 **던지지 않고** 값의 `code` 로 온다. 값이 아예
 *   없으면(`undefined`) 창이 리다이렉트로 페이지를 떠났다는 뜻이다(모바일).
 * - `threw` — 창이 뜨기도 전에 실패했다. 포트원 오류(요청 값이 틀렸다)인지, 그 밖(SDK 스크립트·청크를 못 받았다)인지가
 *   다음 행동을 가른다. */
export type PortOneCallResult =
  | { type: "returned"; response: { code?: string | undefined } | undefined }
  | { type: "threw"; isPortOneError: boolean };

/** - `succeeded` — 창이 성공으로 닫혔다. 결제는 서버가 포트원에 다시 물어 확정한다(브라우저 결과를 믿지 않는다).
 * - `redirecting` — 페이지가 떠난다. 돌아온 주소의 쿼리가 결과를 싣는다.
 * - `notCompleted` — 창이 실패 코드로 닫혔다. 이용자가 창을 닫은 것과 결제사가 거절한 것이 같은 모양이라 둘을 가르지
 *   않고 "완료되지 않았다"는 사실만 말한다 — 이용자가 그만둔 것에 오류를 띄우면 거짓이다.
 * - `failed` — 창을 띄울 요청이 거절됐다. 다시 눌러도 같으므로 문의로 보낸다.
 * - `sdkUnavailable` — SDK 를 못 불러왔다. 로더가 실패한 시도를 페이지 수명 동안 기억해 다시 눌러도 같은 실패라,
 *   새로고침이 유일한 길이다. */
export type PortOneOutcome = "succeeded" | "redirecting" | "notCompleted" | "failed" | "sdkUnavailable";

export function classifyPortOneOutcome(result: PortOneCallResult): PortOneOutcome {
  if (result.type === "threw") return result.isPortOneError ? "failed" : "sdkUnavailable";
  if (result.response === undefined) return "redirecting";
  return result.response.code === undefined ? "succeeded" : "notCompleted";
}
