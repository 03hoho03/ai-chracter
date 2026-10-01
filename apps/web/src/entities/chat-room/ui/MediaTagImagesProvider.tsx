import { createContext, useContext, type ReactNode } from "react";

import type { MediaTagImages } from "@/entities/media-book/@x/chat-room";

type MediaTagImagesProviderProps = {
  /** 글 속 칸 id 형태 태그가 가리키는 그림(`{칸 id: 그림}`). 맵에 없는 칸의 태그는 빈칸이 된다. */
  images: MediaTagImages;
  children: ReactNode;
};

const MediaTagImagesContext = createContext<MediaTagImages | undefined>(undefined);

/**
 * 이 안의 `ChatMarkdown` 만 글 속 미디어 북 태그를 그림으로 그린다. 맵은 서버가 작성자 글(첫 메시지·에필로그)에
 * 대해서만 주므로 그 메시지만 감싼다 — 사용자 메시지와 스트리밍 응답은 감싸지 않아 태그가 글자로 남는다.
 * 맵을 props 가 아니라 컨텍스트로 넘기는 이유: `ChatMarkdown` 은 원시값 props 의 얕은 비교로 다시 그리기를 건너뛰는데,
 * 객체 prop 을 더하면 그 비교가 매번 깨진다.
 */
export function MediaTagImagesProvider({ images, children }: MediaTagImagesProviderProps) {
  return <MediaTagImagesContext.Provider value={images}>{children}</MediaTagImagesContext.Provider>;
}

/** 감싼 자리면 그림 맵, 아니면 undefined(태그를 그리지 않는다). */
export function useMediaTagImages(): MediaTagImages | undefined {
  return useContext(MediaTagImagesContext);
}
