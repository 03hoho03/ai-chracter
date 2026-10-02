import { useEffect, useMemo, useRef } from "react";

import type { StoryDraftContent } from "@/entities/content";
import { nextThumbnailUrlEntry, type ThumbnailUrlEntry } from "@/features/build-story";

export type MediaBookThumbnails = {
  /** 자산의 썸네일 주소. 저장 응답이 새로 서명한 주소보다 이미 쓰던 주소를 먼저 쓴다(깜빡임 방지). */
  resolveUrl: (assetId: string, fallbackUrl?: string) => string | undefined;
  /** 이 기기에서 방금 올린 파일의 로컬 주소를 그 자산의 썸네일로 기억하고 돌려준다. 기억만 하고 다시 그리지는
   * 않는다 — 호출부가 곧이어 폼에 그 자산을 쓰고, 폼 값을 지켜보는 칸이 그때 다시 그려지며 이 주소를 읽는다. */
  rememberUploadedFile: (assetId: string, file: File) => string;
  /** 생성 이미지 목록에서 고른 그림의 서명 주소를 그 자산의 썸네일로 기억한다. */
  rememberPickedUrl: (assetId: string, url: string) => void;
  /**
   * 빌더 셸이 내려가면 끊기는 신호. 이름은 썸네일 저장소지만 셸 수명을 아는 유일한 미디어 북 자리라, 탭보다 오래
   * 사는 미디어 북 작업(일괄 업로드)이 여기서 멈출 때를 안다 — 탭을 옮기는 것은 셸이 남아 있어 끊기지 않는다.
   * 작업을 시작할 때 한 번 받아 들고 다닌다.
   */
  getShellSignal: () => AbortSignal;
};

/**
 * 미디어 북 칸 썸네일 주소를 빌더 셸 높이에서 붙잡아 둔다. 탭을 옮기면 탭 본문이 언마운트되므로 탭 안에 두면 방금
 * 올린 파일의 로컬 주소를 잃는다. 자동저장 응답(`draft`)의 서명 주소는 서버의 15분 구간이 바뀌면 같은 자산이라도
 * 달라지지만, 받은 지 얼마 안 된 주소를 계속 써서 `<img>` 가 다시 받지 않게 한다(규칙은 `nextThumbnailUrlEntry`).
 * 셸이 직접 부르는 훅이다 — 대화 미리보기의 첫 메시지 그림도 같은 주소를 써야 해서 셸이 값을 쥐고 아래로 내려 준다.
 */
export function useMediaBookThumbnailsStore(draft: StoryDraftContent): MediaBookThumbnails {
  const entriesRef = useRef(new Map<string, ThumbnailUrlEntry>());
  const objectUrlsRef = useRef<string[]>([]);
  const shellLifetimeRef = useRef<AbortController>(undefined);

  useEffect(() => {
    const objectUrls = objectUrlsRef.current;
    return () => objectUrls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  // 효과 안에서 만든다 — 개발 모드의 마운트→언마운트→재마운트가 첫 신호를 끊어도 다시 마운트될 때 새 신호가 선다.
  useEffect(() => {
    const controller = new AbortController();
    shellLifetimeRef.current = controller;
    return () => controller.abort();
  }, []);

  const serverCells = draft.mediaBook?.cells;
  const offeredUrlByAssetId = useMemo(
    () => new Map((serverCells ?? []).map((cell) => [cell.imageAssetId, cell.imageUrl])),
    [serverCells],
  );

  return useMemo<MediaBookThumbnails>(
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
      // 마운트 효과가 돌기 전에는 사용자가 무엇도 시작할 수 없어 비어 있을 일이 없다 — 타입만 채운다.
      getShellSignal: () => shellLifetimeRef.current?.signal ?? new AbortController().signal,
    }),
    [offeredUrlByAssetId],
  );
}
