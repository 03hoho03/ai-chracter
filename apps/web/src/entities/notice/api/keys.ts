export const noticeKeys = {
  all: ["notice"] as const,
  list: () => [...noticeKeys.all, "list"] as const,
  detail: (id: string) => [...noticeKeys.all, "detail", id] as const,
};
