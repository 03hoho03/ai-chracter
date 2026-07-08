export const characterImageArchiveKeys = {
  all: ["character-image-archive"] as const,
  list: (characterId: string) => [...characterImageArchiveKeys.all, "list", characterId] as const,
};
