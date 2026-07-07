export const draftKeys = {
  all: ["draft"] as const,
  list: () => [...draftKeys.all, "list"] as const,
};
