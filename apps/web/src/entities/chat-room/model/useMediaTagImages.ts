import { createContext, useContext } from "react";

import type { MediaTagImages } from "@/entities/media-book/@x/chat-room";

/** `MediaTagImagesProvider` 가 채우는 그림 맵 컨텍스트. */
export const MediaTagImagesContext = createContext<MediaTagImages | undefined>(undefined);

/** 감싼 자리면 그림 맵, 아니면 undefined(태그를 그리지 않는다). */
export function useMediaTagImages(): MediaTagImages | undefined {
  return useContext(MediaTagImagesContext);
}
