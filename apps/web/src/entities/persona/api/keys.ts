export const personaKeys = {
  all: ["persona"] as const,
  list: () => [...personaKeys.all, "list"] as const,
};
