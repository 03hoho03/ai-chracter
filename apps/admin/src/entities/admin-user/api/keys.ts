export type AdminUserListParams = {
  page: number;
  q?: string;
  suspended?: boolean;
  beta?: boolean;
};

export const adminUserKeys = {
  all: ["admin-user"] as const,
  /** 요청에 실리는 필터는 전부 키에 들어가야 한다 — 하나라도 빠지면 그 필터만 바꾼 두 목록이 같은
   * 캐시를 공유해 필터를 눌러도 이전 결과가 그대로 보인다(타입 에러도 나지 않는다). */
  list: (params: AdminUserListParams) =>
    [
      ...adminUserKeys.all,
      "list",
      params.page,
      params.q ?? "",
      params.suspended ?? "all",
      params.beta ?? "all",
    ] as const,
  detail: (id: string) => [...adminUserKeys.all, "detail", id] as const,
  /** 원장은 상세 응답에 얹지 않고 별도 라우트다(상세가 이미 목록 셋을
   * 싣고 있다). `all` 하위라 지급·회수 뮤테이션의 `invalidateQueries({ queryKey: all })` 한 줄이
   * 잔액(상세)과 원장을 함께 끊는다. */
  cloverLedger: (id: string, page: number) => [...adminUserKeys.all, "clover-ledger", id, page] as const,
  /** 구매 내역·환불 견적도 `all` 하위다 — 환불 실행이 잔액·원장·구매 상태·견적을 함께 바꾸므로 같은 한 줄로 끊긴다. */
  payments: (id: string) => [...adminUserKeys.all, "payments", id] as const,
  /** 견적 요청에 실리는 접수일·회사 귀책을 전부 키에 넣는다(위 `list` 와 같은 이유). */
  refundQuote: (paymentId: string, receivedOn: string, companyFault: boolean) =>
    [...adminUserKeys.all, "refund-quote", paymentId, receivedOn, companyFault] as const,
};
