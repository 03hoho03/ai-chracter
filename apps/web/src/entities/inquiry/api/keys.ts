export const inquiryKeys = {
  all: ["inquiry"] as const,
  list: () => [...inquiryKeys.all, "list"] as const,
  detail: (id: string) => [...inquiryKeys.all, "detail", id] as const,
};
