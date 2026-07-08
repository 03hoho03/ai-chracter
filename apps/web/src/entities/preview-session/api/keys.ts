export const previewSessionKeys = {
  all: ["preview-session"] as const,
  detail: (previewSessionId: string) => [...previewSessionKeys.all, "detail", previewSessionId] as const,
};
