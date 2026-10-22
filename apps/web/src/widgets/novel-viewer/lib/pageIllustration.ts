import { MEDIA_IMAGE_MAX_HEIGHT_PX } from "@/shared/ui/media-image-frame/MediaImageFrame";

import { PAGE_TEXT_WIDTH_PX } from "./pageFormat";

/** 크기를 모르는 그림의 칸 비율(가로:세로). 스크롤 모드 글 속 그림의 고정 웰과 같은 3:4 다. */
const UNKNOWN_RATIO = { width: 3, height: 4 };

export type PageIllustrationBox = { width: number; height: number };

/**
 * 판형 안 그림 상자의 크기(판형 px). 높이 상한은 스크롤 모드 글 속 그림과 같은 값이고 폭은 글 상자 폭에 걸린다 —
 * 두 모드에서 같은 그림이 같은 크기로 선다. 크기를 모르면 고정 3:4 칸이다.
 *
 * 너비·높이를 둘 다 px 로 정해 판형 안에 그대로 쓴다. 판형 안에서 rem·퍼센트 칸을 쓰면 브라우저 기본 글자 크기가 그림
 * 높이를 바꿔 같은 화·같은 설정의 쪽 수가 기기마다 달라진다. 입력은 응답의 그림 크기와 상수뿐이라 그림이 늦게 도착해도
 * 상자가 그대로이고, 읽던 쪽의 글이 밀리지 않는다.
 *
 * 폭은 내림으로 정한다 — 올림이면 높이가 상한을 1px 넘을 수 있다.
 */
export function toPageIllustrationBox(width: number | null, height: number | null): PageIllustrationBox {
  const ratio = width && height && width > 0 && height > 0 ? { width, height } : UNKNOWN_RATIO;
  const boxWidth = Math.max(1, Math.min(PAGE_TEXT_WIDTH_PX, Math.floor((MEDIA_IMAGE_MAX_HEIGHT_PX * ratio.width) / ratio.height)));
  const boxHeight = Math.min(MEDIA_IMAGE_MAX_HEIGHT_PX, Math.round((boxWidth * ratio.height) / ratio.width));
  return { width: boxWidth, height: boxHeight };
}
