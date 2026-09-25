export type AdminUserListParams = {
  page: number;
  q?: string;
  suspended?: boolean;
};

export const adminUserKeys = {
  all: ["admin-user"] as const,
  list: (params: AdminUserListParams) =>
    [...adminUserKeys.all, "list", params.page, params.q ?? "", params.suspended ?? "all"] as const,
  detail: (id: string) => [...adminUserKeys.all, "detail", id] as const,
  /** 원장은 상세 응답에 얹지 않고 별도 라우트다(상세가 이미 목록 셋을
   * 싣고 있다). `all` 하위라 지급·회수 뮤테이션의 `invalidateQueries({ queryKey: all })` 한 줄이
   * 잔액(상세)과 원장을 함께 끊는다. */
  cloverLedger: (id: string, page: number) => [...adminUserKeys.all, "clover-ledger", id, page] as const,
};
