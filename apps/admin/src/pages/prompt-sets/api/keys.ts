export const promptSetKeys = {
  all: ["promptSets"] as const,
  draft: () => [...promptSetKeys.all, "draft"] as const,
  preview: () => [...promptSetKeys.all, "preview"] as const,
  list: () => [...promptSetKeys.all, "list"] as const,
  detail: (id: string) => [...promptSetKeys.all, "detail", id] as const,
};
