import type { ReactNode } from "react";

import { MediaBookThumbnailsContext } from "../model/useMediaBookThumbnails";
import type { MediaBookThumbnails } from "../model/useMediaBookThumbnailsStore";

type MediaBookThumbnailsProviderProps = {
  value: MediaBookThumbnails;
  children: ReactNode;
};

/** 셸이 쥔 썸네일 주소 저장소를 탭 본문에 내려 준다. */
export function MediaBookThumbnailsProvider({ value, children }: MediaBookThumbnailsProviderProps) {
  return <MediaBookThumbnailsContext.Provider value={value}>{children}</MediaBookThumbnailsContext.Provider>;
}
