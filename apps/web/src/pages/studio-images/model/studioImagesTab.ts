export const STUDIO_IMAGES_TABS = ["generate", "library"] as const;
export type StudioImagesTab = (typeof STUDIO_IMAGES_TABS)[number];

export function isStudioImagesTab(value: string): value is StudioImagesTab {
  return STUDIO_IMAGES_TABS.some((tab) => tab === value);
}
