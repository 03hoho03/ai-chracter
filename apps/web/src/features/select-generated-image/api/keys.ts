export const generatedImagesKeys = {
  all: ["generated-images"] as const,
  list: () => [...generatedImagesKeys.all, "list"] as const,
};
