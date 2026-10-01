import type { CSSProperties } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";

export type MediaImageSurface = "muted" | "secondary";

type MediaImageFrameProps = {
  url: string;
  /** 자산의 픽셀 크기. 둘 다 있어야 원본 비율로 그리고, 하나라도 없으면 고정 3:4 웰로 그린다. */
  width?: number;
  height?: number;
  alt: string;
  /**
   * 그림이 오기 전 자리를 채우는 면. `bg-muted` 는 card·popover 면과 값이 같아 그 위에서 사라지므로, 다이얼로그나
   * 옅은 상자 안에서는 `secondary` 를 준다. 기본값을 두지 않는다 — 면 선택이 이 파일 안 기본값에 숨으면 표면 계약
   * 테스트(파일 단위로 `bg-muted` 를 찾는다)가 다이얼로그 안 호출부를 못 본다. 호출부가 놓인 면을 보고 고른다.
   */
  surface: MediaImageSurface;
};

/** 원본 비율 그림의 높이 상한. 고정 웰(`h-80`)과 같은 값이라 비율을 아는 그림과 모르는 그림이 같은 키로 선다. */
export const MEDIA_IMAGE_MAX_HEIGHT_PX = 320;

const SURFACE_CLASS: Record<MediaImageSurface, string> = {
  muted: "bg-muted",
  secondary: "bg-secondary",
};

/**
 * 본문 사이에 블록으로 서는 그림(채팅의 상황 이미지·글 속 미디어 북 태그 그림, 상세의 글 속 그림). 크롭 없이
 * `object-contain` 으로 담는다.
 */
export function MediaImageFrame({ url, width, height, alt, surface }: MediaImageFrameProps) {
  const sizedStyle = mediaImageFrameStyle(width, height);

  // 크기를 모르는 그림은 고정 3:4 웰이다. 이 자리에 오던 그림(캐릭터 상황 이미지 — 시드·생성물 768x1024)은 세로가
  // 길어서, 높이(`h-80`)를 못박아 어느 폭에서든 240x320 웰이 되게 한다(폭을 못박으면 컬럼 폭에 따라 비율이 흔들려
  // 레터박스가 생긴다). `max-w-3/4` 는 컬럼이 320px보다 좁을 때만 걸리는 안전장치다. `self-start` 는 부모의 stretch 를
  // 걷어 `aspect-ratio` 가 실제 폭을 계산하게 한다.
  return (
    <div
      className={cn(
        sizedStyle === undefined
          ? "self-start aspect-3/4 h-80 max-w-3/4 overflow-hidden rounded-lg"
          : "self-start overflow-hidden rounded-lg",
        SURFACE_CLASS[surface],
      )}
      style={sizedStyle}
    >
      <img src={url} alt={alt} loading="lazy" decoding="async" className="size-full object-contain" />
    </div>
  );
}

/**
 * 원본 비율 그림의 틀 크기. 그림이 도착하기 전에 높이를 잡아야 읽던 글이 밀리지 않으므로(CLS) 비율과 폭을 미리 정한다.
 * - 폭은 "높이가 상한에 닿는 폭"으로 못박고 `max-width: 100%` 로 컬럼에 맞춰 줄인다. 높이는 비율이 정한다.
 *   `aspect-ratio` 에 `max-height` 를 걸면 폭이 줄지 않아 그림이 잘리거나 레터박스가 생기므로 캡은 폭 쪽에 둔다.
 * - 폭을 퍼센트(`w-full`)로 두지 않는 이유: 채팅 본문 컨테이너는 내용 폭만큼만 차지하는(shrink-to-fit) 상자라,
 *   퍼센트 폭은 그 계산에서 0으로 취급돼 그림이 오기 전 틀이 납작해진다.
 * 크기를 모르면(값이 없거나 0 이하) undefined.
 */
export function mediaImageFrameStyle(
  width: number | undefined,
  height: number | undefined,
): CSSProperties | undefined {
  if (!width || !height || width <= 0 || height <= 0) return undefined;
  return {
    aspectRatio: `${width} / ${height}`,
    width: `${Math.round((MEDIA_IMAGE_MAX_HEIGHT_PX * width) / height)}px`,
    maxWidth: "100%",
  };
}
