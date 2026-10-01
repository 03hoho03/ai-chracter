import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

import type { StoryDraftContent } from "@/entities/content";
import { nextThumbnailUrlEntry, type ThumbnailUrlEntry } from "@/features/build-story";

type MediaBookThumbnails = {
  /** 자산의 썸네일 주소. 저장 응답이 새로 서명한 주소보다 이미 쓰던 주소를 먼저 쓴다(깜빡임 방지). */
  resolveUrl: (assetId: string, fallbackUrl?: string) => string | undefined;
  /** 이 기기에서 방금 올린 파일의 로컬 주소를 그 자산의 썸네일로 기억하고 돌려준다. 기억만 하고 다시 그리지는
   * 않는다 — 호출부가 곧이어 폼에 그 자산을 쓰고, 폼 값을 지켜보는 칸이 그때 다시 그려지며 이 주소를 읽는다. */
  rememberUploadedFile: (assetId: string, file: File) => string;
  /** 생성 이미지 목록에서 고른 그림의 서명 주소를 그 자산의 썸네일로 기억한다. */
  rememberPickedUrl: (assetId: string, url: string) => void;
};

const MediaBookThumbnailsContext = createContext<MediaBookThumbnails | undefined>(undefined);

type MediaBookThumbnailsProviderProps = {
  draft: StoryDraftContent;
  children: ReactNode;
};

/**
 * 미디어 북 칸 썸네일 주소를 빌더 셸 높이에서 붙잡아 둔다. 탭을 옮기면 탭 본문이 언마운트되므로 탭 안에 두면 방금
 * 올린 파일의 로컬 주소를 잃는다. 자동저장 응답(`draft`)이 올 때마다 새로 서명된 주소가 들어오지만, 같은 자산이면
 * 받은 지 얼마 안 된 주소를 계속 써서 `<img>` 가 다시 받지 않게 한다(규칙은 `nextThumbnailUrlEntry`).
 */
export function MediaBookThumbnailsProvider({ draft, children }: MediaBookThumbnailsProviderProps) {
  const entriesRef = useRef(new Map<string, ThumbnailUrlEntry>());
  const objectUrlsRef = useRef<string[]>([]);

  useEffect(() => {
    const objectUrls = objectUrlsRef.current;
    return () => objectUrls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const serverCells = draft.mediaBook?.cells;
  const offeredUrlByAssetId = useMemo(
    () => new Map((serverCells ?? []).map((cell) => [cell.imageAssetId, cell.imageUrl])),
    [serverCells],
  );

  const value = useMemo<MediaBookThumbnails>(
    () => ({
      resolveUrl: (assetId, fallbackUrl) => {
        const entry = nextThumbnailUrlEntry(
          entriesRef.current.get(assetId),
          offeredUrlByAssetId.get(assetId) ?? fallbackUrl,
          Date.now(),
        );
        if (entry !== undefined) entriesRef.current.set(assetId, entry);
        return entry?.url;
      },
      rememberUploadedFile: (assetId, file) => {
        const url = URL.createObjectURL(file);
        objectUrlsRef.current.push(url);
        entriesRef.current.set(assetId, { url, receivedAt: Date.now(), canExpire: false });
        return url;
      },
      rememberPickedUrl: (assetId, url) => {
        entriesRef.current.set(assetId, { url, receivedAt: Date.now(), canExpire: true });
      },
    }),
    [offeredUrlByAssetId],
  );

  return <MediaBookThumbnailsContext.Provider value={value}>{children}</MediaBookThumbnailsContext.Provider>;
}

export function useMediaBookThumbnails(): MediaBookThumbnails {
  const context = useContext(MediaBookThumbnailsContext);
  if (context === undefined) throw new Error("useMediaBookThumbnails must be used inside MediaBookThumbnailsProvider");
  return context;
}
