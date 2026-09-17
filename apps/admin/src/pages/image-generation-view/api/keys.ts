export const imageGenerationDetailKeys = {
  all: ["image-generation-detail"] as const,
  list: (userId: string, page: number) => [...imageGenerationDetailKeys.all, "list", userId, page] as const,
};
