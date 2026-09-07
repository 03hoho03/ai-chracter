export const noticeKeys = {
  all: ["notice"] as const,
  list: (page: number) => [...noticeKeys.all, "list", page] as const,
  detail: (id: string) => [...noticeKeys.all, "detail", id] as const,
};
