import type { MeResponse } from "@/entities/session";

/** 탈퇴 확인의 유료 클로버 경고. 남은 유료 클로버(구매로 받은 유료·보너스)는 탈퇴하면 사라지고, 환불은 탈퇴하기 전에
 * 신청해야 한다(상품 안내·환불정책의 같은 문장).
 *
 * 값은 `GET /me` 의 `paidCloverBalance` 다 — 재동의 게이트 밖이라 재동의 모달의 "동의하지 않고 탈퇴"에서도 읽힌다.
 * 세션을 못 읽었으면(로딩·실패) 경고를 빼지 않고 숫자 없이 띄운다 — 유료 회원이 경고 없이 떠나는 쪽이 무료 회원이
 * 불필요한 문장을 한 번 읽는 쪽보다 비싸다. */
export type PaidBalanceWarning = { kind: "none" } | { kind: "count"; paidBalance: number } | { kind: "unknown" };

export function getPaidBalanceWarning(me: Pick<MeResponse, "paidCloverBalance"> | undefined): PaidBalanceWarning {
  if (me === undefined) return { kind: "unknown" };
  return me.paidCloverBalance > 0 ? { kind: "count", paidBalance: me.paidCloverBalance } : { kind: "none" };
}
