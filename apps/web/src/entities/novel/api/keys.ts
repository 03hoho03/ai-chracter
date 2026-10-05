export const novelKeys = {
  all: ["novel"] as const,
  list: () => [...novelKeys.all, "list"] as const,
  detail: (novelId: string) => [...novelKeys.all, "detail", novelId] as const,
  job: (novelId: string, jobId: string) => [...novelKeys.all, "job", novelId, jobId] as const,
};
