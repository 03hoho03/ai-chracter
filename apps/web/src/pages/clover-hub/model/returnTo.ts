import { resolvePaymentRedirect, type SettledPurchase } from "@/features/purchase-clover";

import type { CloverHubSearch } from "./cloverHubSearch";

/** 제어문자(0x00-0x1f, 0x7f). 브라우저는 URL 을 해석하기 전에 탭·개행을 지워 "/<탭>/evil" 을 "//evil" 로 읽는다. */
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/;

/** 충전 화면 자신과 그 아래 경로. `/clover/pricing` 도 이 화면으로 넘겨지므로 되돌아오는 길이 된다. */
const CLOVER_HUB_PATH = /^\/clover(?:[/?#]|$)/;

/** `?returnTo=` 로 받은 복귀 주소를 이 사이트 안의 경로로만 받는다. 어긋나면 조용히 버린다(링크를 그리지 않는다).
 *
 * 규칙은 서버의 로그인 복귀 검사(`apps/api/src/api/auth/oauth_common.py` 의 `safe_redirect_path`)와 같다 — "/" 로 시작하고,
 * "//"(프로토콜 상대 주소)로 시작하지 않고, 역슬래시가 어디에도 없고(브라우저는 "\" 를 "/" 로 읽는다), 제어문자가 없다.
 * 스킴이 붙은 주소("https:", "javascript:")는 "/" 로 시작하지 않아 첫 조건에 걸린다. 여기에 충전 화면 자신을 더 막는다 —
 * 충전 화면으로 "돌아가기"는 같은 화면을 다시 그릴 뿐이다. */
export function parseReturnTo(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return undefined;
  if (CONTROL_CHARACTER.test(value)) return undefined;
  if (CLOVER_HUB_PATH.test(value)) return undefined;
  return value;
}

/** 이 화면이 쓸 복귀 주소. 주소의 `?returnTo=`(충전 링크·로그인 왕복이 싣는다)가 먼저이고, 없으면 결제창에서 돌아온
 * 진입(성공·미완료)에 한해 결제창을 띄우기 전에 탭 저장소에 둔 값을 쓴다 — 결제창의 돌아올 주소에는 쿼리를 싣지 않는다.
 * 결제창 복귀가 아닌 진입에는 앞 결제가 남긴 값을 쓰지 않는다. 탭 저장소 값도 같은 검사를 거친다. */
export function resolveHubReturnTo(
  search: Pick<CloverHubSearch, "returnTo" | "paymentId" | "code">,
  storedReturnTo: string | undefined,
): string | undefined {
  if (search.returnTo !== undefined) return search.returnTo;
  if (resolvePaymentRedirect(search).kind === "none") return undefined;
  return parseReturnTo(storedReturnTo);
}

/** 복귀 링크의 라벨. 채팅 방에서 왔으면 대화로, 그 밖(웹소설 화 구매 등)이면 이전 화면으로 돌아간다고 말한다. */
export function returnLinkLabel(returnTo: string): string {
  return returnTo.startsWith("/chat/") ? "대화로 돌아가기" : "이전 화면으로 돌아가기";
}

/** 복귀 길을 어디에 둘지. 결제 전·미완료·확인 중에는 화면 머리의 텍스트 링크(충전하지 않고 돌아가는 길)이고, 충전에
 * 성공하면 결과 블록의 솔리드 버튼 하나로 바꾼다 — 같은 목적지를 두 자리에 두지 않고, 이 화면의 솔리드 채움은 성공 뒤의
 * 이 버튼 하나뿐이다. */
export function getReturnPlacement(
  result: SettledPurchase["result"] | null,
  returnTo: string | undefined,
): { head: boolean; solid: boolean } {
  if (returnTo === undefined) return { head: false, solid: false };
  const isPaid = result === "paid";
  return { head: !isPaid, solid: isPaid };
}
