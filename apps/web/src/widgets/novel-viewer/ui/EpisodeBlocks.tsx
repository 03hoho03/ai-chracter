import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageOff } from "lucide-react";

import { MediaImageFrame } from "@/shared/ui/media-image-frame/MediaImageFrame";

import type { PageTypography } from "../lib/pageFormat";
import { toPageIllustrationBox } from "../lib/pageIllustration";
import type { ReaderBlock } from "../lib/readerBlocks";
import type { ViewerIllustration } from "../model/viewerSource";

/** 그림의 대체 글. 설명 글 칸은 응답에 없어 문단 사이에서 "삽화"로만 읽힌다. */
const ILLUSTRATION_ALT = "삽화";
const ORIGINAL_CAPTION = "원작 이미지";

type PagedEpisodeBlocksProps = {
  paragraphs: readonly string[];
  blocks: readonly ReaderBlock[];
  /** 보기 설정에서 나온 판형 안 조판값(px). */
  typography: PageTypography;
};

/**
 * 판형 안 화 본문 — 문단과 그 사이 삽화. 블록 흐름이고 블록 간격은 아래 여백이다(본문 마지막 블록은 0 — 화 끝은 따로
 * 한 쪽이라 뒤에 간격이 필요 없다. 마지막 문단 뒤에 그림이 있으면 그 문단은 간격을 가진다). WebKit 은 다단 안의 flex
 * 항목을 줄 경계가 아니라 단 높이에서 잘라 나눠 단 위·아래에 줄이 반쯤 잘려 그려지고, 다단 폭을 바꿀 때 쪽 나눔도
 * 달라진다. 블록 문단은 줄 단위로 나뉜다(엔진 둘 다 실측). 그림 블록도 블록이고 쪽에 걸쳐 쪼개지지 않는다.
 *
 * 문단에만 `data-paragraph-index` 를 단다 — 쪽 나누기·읽은 자리가 이 속성만 세어 순번이 곧 문단 번호다. 그림 블록은
 * 대신 자기 자리(문단·앞뒤·키)를 단다.
 */
export function PagedEpisodeBlocks({ paragraphs, blocks, typography }: PagedEpisodeBlocksProps) {
  return (
    <div className="text-foreground" style={{ fontSize: typography.fontSizePx, lineHeight: typography.lineHeight }}>
      {blocks.map((block, position) => {
        const marginBottom = position === blocks.length - 1 ? 0 : typography.paragraphGapPx;
        if (block.kind === "illustration") {
          return (
            <PageIllustrationBlock key={block.key} blockKey={block.key} illustration={block.illustration} marginBottom={marginBottom} />
          );
        }
        // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도 이 순번으로
        // 저장한다).
        return (
          <p
            key={`paragraph-${block.index}`}
            data-paragraph-index={block.index}
            className="whitespace-pre-line text-pretty break-keep"
            style={{ marginBottom }}
          >
            {paragraphs[block.index]}
          </p>
        );
      })}
    </div>
  );
}

/**
 * 판형 안 그림 블록. 상자 크기는 응답의 그림 크기로 미리 정한 px 라(`toPageIllustrationBox`) 그림이 늦게 와도 쪽 나눔이
 * 그대로다. 캡션·안내 글자도 px 다 — 판형 안이 브라우저 기본 글자 크기를 따르면 쪽 수가 바뀐다. 사유 안내는 세 줄에서
 * 자른다 — 운영자 사유에 길이 상한이 없어 한 단보다 길어지면 쪽에 걸쳐 쪼개지지 않는 블록이 단 아래에서 잘린다.
 */
function PageIllustrationBlock({
  blockKey,
  illustration,
  marginBottom,
}: {
  blockKey: string;
  illustration: ViewerIllustration;
  marginBottom: number;
}) {
  const placementProps = {
    "data-illustration-key": blockKey,
    "data-illustration-paragraph": illustration.paragraphIndex,
    "data-illustration-placement": illustration.placement,
  };

  if (illustration.withheld !== null) {
    return (
      <div {...placementProps} className="break-inside-avoid" style={{ marginBottom }}>
        <WithheldNotice illustration={illustration} isInPageFormat />
      </div>
    );
  }

  const box = toPageIllustrationBox(illustration.width, illustration.height);
  return (
    <figure {...placementProps} className="break-inside-avoid" style={{ marginBottom }}>
      <div className="overflow-hidden rounded-lg bg-muted" style={{ width: box.width, height: box.height }}>
        {illustration.url !== null && (
          <img
            src={illustration.url}
            alt={ILLUSTRATION_ALT}
            loading="lazy"
            decoding="async"
            draggable={false}
            className="size-full object-contain"
          />
        )}
      </div>
      {illustration.source === "original" && (
        <figcaption className="mt-[6px] text-[12px]/[16px] font-medium text-muted-foreground">{ORIGINAL_CAPTION}</figcaption>
      )}
    </figure>
  );
}

type ScrollEpisodeBlocksProps = {
  paragraphs: readonly string[];
  blocks: readonly ReaderBlock[];
};

/** 스크롤 모드 화 본문 — 문단과 그 사이 삽화. 글 속 그림 블록(`MediaImageFrame`)이 크기를 알면 비율로, 모르면 고정
 * 칸으로 자리를 먼저 잡아 그림이 늦게 와도 읽던 글이 밀리지 않는다. 사유 안내는 자르지 않는다. */
export function ScrollEpisodeBlocks({ paragraphs, blocks }: ScrollEpisodeBlocksProps) {
  return (
    <div className="flex flex-col gap-4 text-foreground">
      {blocks.map((block) => {
        if (block.kind === "illustration") {
          const { illustration } = block;
          if (illustration.withheld !== null) return <WithheldNotice key={block.key} illustration={illustration} isInPageFormat={false} />;
          return (
            <figure key={block.key}>
              {illustration.url === null ? (
                <div aria-hidden className="aspect-3/4 h-80 max-w-3/4 rounded-lg bg-muted" />
              ) : (
                <MediaImageFrame
                  url={illustration.url}
                  width={illustration.width ?? undefined}
                  height={illustration.height ?? undefined}
                  alt={ILLUSTRATION_ALT}
                  surface="muted"
                  isDraggable={false}
                />
              )}
              {illustration.source === "original" && (
                <figcaption className="mt-1.5 text-xs font-medium text-muted-foreground">{ORIGINAL_CAPTION}</figcaption>
              )}
            </figure>
          );
        }
        // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도 이 순번으로
        // 저장한다).
        return (
          <p
            key={`paragraph-${block.index}`}
            data-paragraph-index={block.index}
            className="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep"
          >
            {paragraphs[block.index]}
          </p>
        );
      })}
    </div>
  );
}

/**
 * 그림 대신 서는 안내 — 운영자가 내린 그림(사유 함께)과 원작이 이용 제한 중인 그림. 소유자와 독자가 같은 안내를 본다
 * (작가도 독자가 무엇을 보는지 알아야 그 그림을 바꾸거나 뗀다). 그림 크기를 지키지 않고 짧은 상자로 선다 — 지키면 한
 * 쪽 거의 전부가 "없는 그림"이 된다. 판형 안이면 px, 스크롤 모드면 평소 크기이고 사유를 자르지 않는다.
 */
function WithheldNotice({ illustration, isInPageFormat }: { illustration: ViewerIllustration; isInPageFormat: boolean }) {
  const isTakenDown = illustration.withheld === "taken_down";
  const title = isTakenDown ? "운영 정책에 따라 내린 그림이에요" : "원작이 이용 제한 중이라 이 그림은 보여 드릴 수 없어요";
  const reason = isTakenDown ? illustration.withheldReason?.trim() : undefined;
  return (
    <div
      role="note"
      className={cn(
        "flex items-start rounded-lg bg-muted break-keep text-muted-foreground",
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
