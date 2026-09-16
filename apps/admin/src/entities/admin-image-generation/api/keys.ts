import type { ImageGenerationStatus, ImageStyle } from "../model/labels";

export type ImageGenerationStatusFilter = ImageGenerationStatus;
export type ImageGenerationStyleFilter = ImageStyle;

export type AdminImageGenerationListParams = {
  page: number;
  q?: string;
  status?: ImageGenerationStatusFilter;
  style?: ImageGenerationStyleFilter;
  from?: string;
  to?: string;
};

export const adminImageGenerationKeys = {
  all: ["admin-image-generation"] as const,
  list: (params: AdminImageGenerationListParams) =>
    [
      ...adminImageGenerationKeys.all,
      "list",
      params.page,
      params.q ?? "",
      params.status ?? "all",
      params.style ?? "all",
      params.from ?? "",
      params.to ?? "",
    ] as const,
};
