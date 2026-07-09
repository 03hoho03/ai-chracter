export const usageMetricsKeys = {
  all: ["usage-metrics"] as const,
  range: (params: { from: string; to: string }) =>
    [...usageMetricsKeys.all, params.from, params.to] as const,
};
