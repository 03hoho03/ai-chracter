import type { AdminCreatorPayoutWithholding } from "../api/useCreatorPayoutQueries";

/**
 * 신청 때 남긴 원천징수와 지금 세율로 다시 계산한 값이 다른가. 다르면 신청 뒤 세율 상수가 바뀐 것이라 화면이 경고한다 —
 * 이체는 신청 때 값으로 한다. 금액이 같아도 세율이 다르면(끝수 절사로 세액이 우연히 같은 경우) 다르다고 본다.
 */
export function isWithholdingChanged(snapshot: AdminCreatorPayoutWithholding, current: AdminCreatorPayoutWithholding) {
  return (
    snapshot.incomeTaxRateBps !== current.incomeTaxRateBps ||
    snapshot.incomeTaxKrw !== current.incomeTaxKrw ||
    snapshot.localTaxKrw !== current.localTaxKrw ||
    snapshot.netAmountKrw !== current.netAmountKrw
  );
}

/** 세율(bps)을 사람이 읽는 퍼센트로. 300 → "3%", 330 → "3.3%". */
export function formatRateBps(rateBps: number) {
  return `${(rateBps / 100).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}%`;
}

/** 어드민 원화 표기(천 단위 구분 + "원"). */
export function formatKrw(amount: number) {
  return `${amount.toLocaleString("ko-KR")}원`;
}
