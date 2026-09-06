export const dashboardKeys = {
  all: ["dashboard"] as const,
  counts: () => [...dashboardKeys.all, "counts"] as const,
  trend: (days: number) => [...dashboardKeys.all, "trend", days] as const,
  popular: (limit: number) => [...dashboardKeys.all, "popular", limit] as const,
  activity: () => [...dashboardKeys.all, "activity"] as const,
};
