import { MESSAGE_BY_CODE } from "@/shared/lib/asset/uploadAssetErrorMessage";

/**
 * 미디어 북 칸에 넣을 수 있는 이미지 형식. 파일 창의 `accept` 와 끌어놓기 검사가 같은 목록을 쓴다 — 파일 창은 고를 수
 * 있는 파일을 거르지만 끌어놓기는 무엇이든 들어오고, GIF 처럼 디코드는 되는 형식이 그대로 올라가지 않게 따로 막아야 한다.
 */
export const MEDIA_BOOK_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;
export const MEDIA_BOOK_IMAGE_ACCEPT = MEDIA_BOOK_IMAGE_TYPES.join(",");

export type DroppedImagePick = { ok: true; file: File } | { ok: false; message: string };

/**
 * 칸 하나에 끌어다 놓은 파일들에서 올릴 한 장을 고른다. 여러 장이면 첫 장을 쓰지 않고 거절한다 — 끌어온 파일의 순서는
 * 운영체제와 고른 순서에 따라 달라 어느 장이 "첫 장" 인지 사용자가 알 수 없고, 나머지가 말없이 버려진다. 여러 장은
 * 파일 이름으로 칸을 찾아 넣는 길이 따로 있어 그리로 안내한다. 크기 상한은 여기서 보지 않는다 — 업로드가 리사이즈 전에
 * 같은 상한으로 검사하고 같은 문구로 알린다.
 */
export function pickDroppedImage(files: readonly File[]): DroppedImagePick {
  if (files.length > 1) {
    return {
      ok: false,
      message: "칸에는 이미지를 한 장씩 놓을 수 있어요. 여러 장은 ‘파일 이름으로 한꺼번에 넣기’로 넣어 주세요.",
    };
  }
  const file = files[0];
  if (!file || !isMediaBookImageType(file.type)) return { ok: false, message: MESSAGE_BY_CODE.DECODE_FAILED };
  return { ok: true, file };
}

/** 끌고 있는 것이 파일인가 — 글자나 화면 요소를 끌 때는 칸이 놓을 자리로 반응하지 않는다. */
export function isFileDrag(types: readonly string[]): boolean {
  return types.includes("Files");
}

function isMediaBookImageType(type: string): boolean {
  return MEDIA_BOOK_IMAGE_TYPES.some((accepted) => accepted === type);
}
