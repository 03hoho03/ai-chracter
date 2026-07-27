export const imageJobKeys = {
  all: ["image-job"] as const,
  status: (jobId: string) => [...imageJobKeys.all, "status", jobId] as const,
};
