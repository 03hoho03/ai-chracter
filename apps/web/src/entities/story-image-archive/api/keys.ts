export const storyImageArchiveKeys = {
  all: ["story-image-archive"] as const,
  list: (storyId: string) => [...storyImageArchiveKeys.all, "list", storyId] as const,
};
