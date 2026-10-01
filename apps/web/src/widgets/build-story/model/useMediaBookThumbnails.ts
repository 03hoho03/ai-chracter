import { createContext, useContext } from "react";

import type { MediaBookThumbnails } from "./useMediaBookThumbnailsStore";

/** `MediaBookThumbnailsProvider` 가 채우는 썸네일 주소 저장소 컨텍스트. */
export const MediaBookThumbnailsContext = createContext<MediaBookThumbnails | undefined>(undefined);

export function useMediaBookThumbnails(): MediaBookThumbnails {
  const context = useContext(MediaBookThumbnailsContext);
  if (context === undefined) throw new Error("useMediaBookThumbnails must be used inside MediaBookThumbnailsProvider");
  return context;
}
