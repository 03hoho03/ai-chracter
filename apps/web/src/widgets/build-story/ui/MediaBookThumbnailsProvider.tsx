import { createContext, useContext, type ReactNode } from "react";

import type { MediaBookThumbnails } from "../model/useMediaBookThumbnailsStore";

type MediaBookThumbnailsProviderProps = {
  value: MediaBookThumbnails;
  children: ReactNode;
};

const MediaBookThumbnailsContext = createContext<MediaBookThumbnails | undefined>(undefined);

/** 셸이 쥔 썸네일 주소 저장소를 탭 본문에 내려 준다. */
export function MediaBookThumbnailsProvider({ value, children }: MediaBookThumbnailsProviderProps) {
  return <MediaBookThumbnailsContext.Provider value={value}>{children}</MediaBookThumbnailsContext.Provider>;
}

export function useMediaBookThumbnails(): MediaBookThumbnails {
  const context = useContext(MediaBookThumbnailsContext);
  if (context === undefined) throw new Error("useMediaBookThumbnails must be used inside MediaBookThumbnailsProvider");
  return context;
}
