export const llmUsageKeys = {
  all: ["llm-usage"] as const,
  range: (params: { from: string; to: string }) => [...llmUsageKeys.all, params.from, params.to] as const,
};
