// 로케일을 "ko-KR"로 고정한다 — 생략하면 브라우저 설정에 따라 천 단위 구분자가 `.`·공백으로 바뀐다.
const KRW_FORMATTER = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

/** 원 단위 금액을 천 단위 구분 표기로 바꾼다(`12345 → "12,345원"`). 음수는 부호를 앞에 둔다(`-1,234원`) — 결제 취소
 * 조정으로 정산 잔액이 음수일 수 있다. 서버가 원 미만을 이미 버린 정수를 주므로 여기서 끝수를 다루지 않는다. */
export function formatKrw(amount: number): string {
  return `${KRW_FORMATTER.format(amount)}원`;
}
