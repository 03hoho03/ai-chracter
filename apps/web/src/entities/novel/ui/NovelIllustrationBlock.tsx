import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageOff } from "lucide-react";

import { MediaImageFrame } from "@/shared/ui/media-image-frame/MediaImageFrame";

import type { ViewerIllustration } from "../model/readerBlocks";

/** 그림의 대체 글. 설명 글 칸은 응답에 없어 문단 사이에서 "삽화"로만 읽힌다. */
export const ILLUSTRATION_ALT = "삽화";
export const ORIGINAL_CAPTION = "원작 이미지";

/** 그림 웰과 안내 상자가 놓인 면. 페이지 배경 위면 `muted`, 모달·카드 위면 `secondary` 다 — `muted` 는 모달 표면과 값이
 * 같아 그 위에서는 웰과 안내 상자가 사라진다. */
export type NovelIllustrationSurface = "muted" | "secondary";

const SURFACE_FILL: Record<NovelIllustrationSurface, string> = {
  muted: "bg-muted",
  secondary: "bg-secondary",
};

/** 글 흐름 속 삽화 한 장(읽기 화면 스크롤 모드, 판 이력). 크기를 알면 비율로, 모르면 고정 칸으로 자리를 먼저 잡아 그림이
 * 늦게 와도 글이 밀리지 않는다. 가려진 그림이면 그림 대신 안내 상자가 선다. 사유 안내는 자르지 않는다. */
export function NovelIllustrationFigure({
  illustration,
  surface,
}: {
  illustration: ViewerIllustration;
  surface: NovelIllustrationSurface;
}) {
  if (illustration.withheld !== null) {
    return <NovelIllustrationWithheldNotice illustration={illustration} isInPageFormat={false} surface={surface} />;
  }
  return (
    <figure>
      {illustration.url === null ? (
        <div aria-hidden className={cn("aspect-3/4 h-80 max-w-3/4 rounded-lg", SURFACE_FILL[surface])} />
      ) : (
        <MediaImageFrame
          url={illustration.url}
          width={illustration.width ?? undefined}
          height={illustration.height ?? undefined}
          alt={ILLUSTRATION_ALT}
          surface={surface}
          isDraggable={false}
        />
      )}
      {illustration.source === "original" && (
        <figcaption className="mt-1.5 text-xs font-medium text-muted-foreground">{ORIGINAL_CAPTION}</figcaption>
      )}
    </figure>
  );
}

/**
 * 그림 대신 서는 안내 — 운영자가 내린 그림(사유 함께)과 원작이 이용 제한 중인 그림. 소유자와 독자가 같은 안내를 본다
 * (작가도 독자가 무엇을 보는지 알아야 그 그림을 바꾸거나 뗀다). 그림 크기를 지키지 않고 짧은 상자로 선다 — 지키면 한
 * 쪽 거의 전부가 "없는 그림"이 된다. 판형 안이면 px 에 사유를 세 줄에서 자르고, 글 흐름 속이면 평소 크기에 자르지 않는다.
 */
export function NovelIllustrationWithheldNotice({
  illustration,
  isInPageFormat,
  surface,
}: {
  illustration: ViewerIllustration;
  isInPageFormat: boolean;
  surface: NovelIllustrationSurface;
}) {
  const isTakenDown = illustration.withheld === "taken_down";
  const title = isTakenDown ? "운영 정책에 따라 내린 그림이에요" : "원작이 이용 제한 중이라 이 그림은 보여 드릴 수 없어요";
  const reason = isTakenDown ? illustration.withheldReason?.trim() : undefined;
  return (
    <div
      role="note"
      className={cn(
        "flex items-start rounded-lg",
        SURFACE_FILL[surface],
        "break-keep text-muted-foreground",
        isInPageFormat ? "gap-[10px] px-[14px] py-[12px] text-[13px]/[18px]" : "gap-2.5 px-3.5 py-3 text-xs",
      )}
    >
      <ImageOff aria-hidden className={cn("shrink-0", isInPageFormat ? "mt-[1px] size-[16px]" : "mt-0.5 size-4")} />
      <span className="min-w-0">
        <span className="block font-medium text-foreground">{title}</span>
        {reason !== undefined && reason !== "" && (
          <span className={cn("block wrap-break-word", isInPageFormat && "line-clamp-3")}>{reason}</span>
        )}
      </span>
    </div>
  );
}
