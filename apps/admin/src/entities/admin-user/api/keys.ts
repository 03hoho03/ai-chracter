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
};
