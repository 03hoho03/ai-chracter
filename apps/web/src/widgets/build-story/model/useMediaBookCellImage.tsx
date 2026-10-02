import { Button } from "@ai-character-chat/ui/components/button";
import { toast } from "sonner";

import {
  cellImageRefusalMessage,
  findCell,
  setCellImage,
  type MediaBookCellImage,
  type MediaBookCellValues,
  type MediaBookValues,
} from "@/features/build-story";
import { uploadAsset } from "@/shared/api/asset/uploadAsset";
import { uploadAssetErrorMessage } from "@/shared/lib/asset/uploadAssetErrorMessage";

import { useMediaBookEditor } from "./useMediaBookEditor";
import { useMediaBookThumbnails } from "./useMediaBookThumbnails";
import type { MediaBookPosition } from "../ui/MediaBookGrid";

/** 칸 이미지를 바꾼 뒤 띄우는 되돌리기 토스트. id 가 하나라 연달아 바꾸면 쌓이지 않고 마지막 교체만 되돌린다. */
export const MEDIA_BOOK_IMAGE_UNDO_TOAST_ID = "media-book-image-undo";
// 기본 4초는 바뀐 이미지를 확인하고 되돌리기를 누르기에 짧다.
const UNDO_TOAST_DURATION_MS = 8000;

/**
 * 칸 하나에 이미지를 올리고 넣는 길. 칸 상세의 버튼(파일 올리기·생성한 이미지에서 고르기)과 배치표 칸에 끌어놓기가 같은
 * 길을 쓴다 — 업로드·썸네일 기억·실패 안내·칸 반영·되돌리기가 입력 방식마다 갈리지 않게.
 *
 * @param focusAfterUndo 되돌리기 버튼이 토스트와 함께 사라질 때 포커스를 둘 곳(표의 그 칸, 보이지 않으면 상세 제목).
 */
export function useMediaBookCellImage(focusAfterUndo: (position: MediaBookPosition, options: FocusOptions) => void) {
  const { getMediaBook, commit } = useMediaBookEditor();
  const thumbnails = useMediaBookThumbnails();

  /** 파일을 올리고 이 기기의 썸네일로 기억한다. 실패하면 사유별 안내를 띄우고 `undefined` 다. */
  async function uploadImage(file: File): Promise<MediaBookCellImage | undefined> {
    try {
      const assetId = await uploadAsset(file, "situational-image");
      return { assetId, imageUrl: thumbnails.rememberUploadedFile(assetId, file) };
    } catch (error) {
      toast.error(uploadAssetErrorMessage(error));
      return undefined;
    }
  }

  /**
   * 그 칸에 이미지를 넣는다(채운 칸이면 이미지만 바꾸고 되돌리기를 띄운다). 칸에 들어갔으면 `true` — 지금 이미지를 다시
   * 고른 경우도 칸에 그 이미지가 있으니 `true` 다.
   */
  function applyImage(position: MediaBookPosition, image: MediaBookCellImage): boolean {
    // 업로드를 기다리는 동안 다른 칸이 채워졌을 수 있다 — 그 순간의 값 위에 쓴다.
    const before = findCell(getMediaBook(), position.personId, position.sceneId);
    // 지금 이미지를 다시 골랐으면 바뀌는 것이 없다(저장도 되돌리기도 띄우지 않는다).
    if (before?.imageAssetId === image.assetId) return true;
    // 업로드를 기다리는 사이 이 칸의 인물·장면이 지워졌거나 상한에 닿았으면 거절된다(없는 축을 가리키는 칸을 만들지 않는다).
    const result = setCellImage(getMediaBook(), position.personId, position.sceneId, image, () => crypto.randomUUID());
    if (!result.ok) {
      toast.error(`${cellImageRefusalMessage(result.reason)}.`);
      return false;
    }
    commit(result.mediaBook);
    if (before) offerUndo(position, before, image.assetId);
    return true;
  }

  /** 확인 없이 바꾸는 대신 직전 이미지 하나로 되돌릴 길을 둔다 — 반복해서 채우는 작업이 확인 창으로 느려지지 않게. */
  function offerUndo(position: MediaBookPosition, previous: MediaBookCellValues, replacedWith: string) {
    const cellName = toCellName(getMediaBook(), position);
    toast(`${cellName} 칸의 이미지를 바꿨어요.`, {
      id: MEDIA_BOOK_IMAGE_UNDO_TOAST_ID,
      duration: UNDO_TOAST_DURATION_MS,
      // sonner 의 기본 동작 버튼은 밝은 면·작은 반경·다크에서 안 보이는 포커스라 이 앱의 버튼을 넘긴다. 토스트 면이
      // popover 라 outline 의 hover 채움(muted)이 사라지므로 secondary 로 올린다.
      action: (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto hover:bg-secondary"
          onClick={() => {
            // 포커스가 토스트를 떠나면 sonner 가 토스트에 들어오기 전 자리(대개 방금 누른 고르기 버튼)로 돌려준다 —
            // 마우스든 Alt+T 키보드든 같다. 그래서 아래에서 칸으로 옮겨도 그 자리가 있으면 곧바로 그리로 간다. 칸으로
            // 옮기는 것은 돌려줄 자리가 없을 때(포커스가 body 였을 때)를 위해서다 — 버튼이 토스트와 함께 사라지며
            // 포커스가 body 로 떨어지지 않게 둔다(화면은 움직이지 않게).
            focusAfterUndo(position, { preventScroll: true });
            toast.dismiss(MEDIA_BOOK_IMAGE_UNDO_TOAST_ID);
            undoImageChange(cellName, previous, replacedWith);
          }}
        >
          되돌리기
        </Button>
      ),
    });
  }

  function undoImageChange(cellName: string, previous: MediaBookCellValues, replacedWith: string) {
    // 그 사이 이 칸을 또 바꿨거나 비웠으면 지금 값을 덮지 않는다.
    const current = findCell(getMediaBook(), previous.personId, previous.sceneId);
    const result =
      current?.imageAssetId === replacedWith
        ? setCellImage(
            getMediaBook(),
            previous.personId,
            previous.sceneId,
            {
              assetId: previous.imageAssetId,
              imageUrl: previous.imageUrl,
              imageWidth: previous.imageWidth,
              imageHeight: previous.imageHeight,
            },
            () => crypto.randomUUID(),
          )
        : undefined;
    if (!result?.ok) {
      toast(`${cellName} 칸이 그 뒤에 바뀌어서 되돌리지 않았어요.`);
      return;
    }
    commit(result.mediaBook);
    toast.success(`${cellName} 칸을 원래 이미지로 되돌렸어요.`);
  }

  return { uploadImage, applyImage };
}

/** 토스트에 쓰는 칸 이름(`유나 · 리딩`). 이미지를 넣은 직후라 두 축이 다 있다. */
function toCellName(mediaBook: MediaBookValues, position: MediaBookPosition): string {
  const person = mediaBook.people.find((item) => item.id === position.personId);
  const scene = mediaBook.scenes.find((item) => item.id === position.sceneId);
  return `${person?.name ?? ""} · ${scene?.name ?? ""}`;
}
