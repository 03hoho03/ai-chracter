import { cn } from "@ai-character-chat/ui/lib/utils";
import { useEffect, useImperativeHandle, type PointerEventHandler, type Ref } from "react";

import type { NovelChapterSummary, NovelDetailResponse } from "@/entities/novel";

import { useIsFinePointer } from "../lib/useIsFinePointer";
import { usePagedReader, type PagedPosition, type PagedReaderHandle } from "../model/usePagedReader";
import type { ReadingPositionSession } from "../model/useReadingPosition";
import { EpisodeEnd } from "./EpisodeEnd";
import { EpisodeHeader } from "./EpisodeHeader";

/** `max-w-prose` 를 재는 탐침의 폭. 상한이 늘 걸리도록 어떤 창보다 넓게 둔다. */
const PROSE_PROBE_WIDTH_PX = 10_000;

type PagedEpisodeBodyProps = {
  ref?: Ref<PagedReaderHandle>;
  novel: NovelDetailResponse;
  summary: NovelChapterSummary;
  episodeLabel: string;
  paragraphs: readonly string[];
  next: NovelChapterSummary | undefined;
  /** 보기 설정(글자 크기·줄 간격·여백)에서 나온 본문 조판 클래스. 좌우 여백은 쪽 안쪽 여백으로 잰다. */
  typographyClassName: string;
  readingPosition: ReadingPositionSession;
  onPositionChange: (position: PagedPosition) => void;
  onPointerDown: PointerEventHandler<HTMLElement>;
  onPointerUp: PointerEventHandler<HTMLElement>;
  onOpenToc: (opener: HTMLElement) => void;
};

/**
 * 쪽을 좌우로 넘겨 읽는 화 본문(페이지 모드). 뷰포트를 채우는 고정 화면이고, 첫 쪽 위에 화 머리를, 본문이 끝나면 화 끝
 * 블록을 따로 한 화면에 둔다. 쪽 나누기·읽은 자리·넘김 전환은 `usePagedReader` 가 맡는다.
 *
 * 넘기는 손짓과 텍스트 선택은 같은 끌기라 함께 살 수 없어 본문 선택을 끈다(복사는 스크롤 모드에서). 가로 오버스크롤은
 * 막아 끝 쪽에서 더 끌어도 브라우저의 뒤로 가기 손짓으로 새지 않게 하고, 터치는 핀치 확대만 브라우저에 남긴다 — 가로
 * 끌기는 넘김이 직접 받는다.
 */
export function PagedEpisodeBody({
  ref,
  novel,
  summary,
  episodeLabel,
  paragraphs,
  next,
  typographyClassName,
  readingPosition,
  onPositionChange,
  onPointerDown,
  onPointerUp,
  onOpenToc,
}: PagedEpisodeBodyProps) {
  const isFinePointer = useIsFinePointer();
  const reader = usePagedReader({
    session: readingPosition,
    paragraphCount: paragraphs.length,
    isFinePointer,
    typographyClassName,
  });

  useImperativeHandle(ref, () => reader.handle);

  useEffect(() => {
    onPositionChange(reader.position);
  }, [reader.position]);

  return (
    <main ref={reader.viewportRef} className="fixed inset-0 overflow-hidden" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
      {/* 잴 때만 쓰는 보이지 않는 탐침. 쪽 상자 상한(`max-w-prose`, 글자 폭 단위라 글자 크기·글꼴마다 다르다)과 여백·줄
          높이를 지금 조판 클래스로 잰다. */}
      <div
        ref={reader.probeRef}
        aria-hidden
        className={cn("pointer-events-none invisible absolute top-0 left-0 max-w-prose", typographyClassName)}
        style={{ width: PROSE_PROBE_WIDTH_PX }}
      />
      {/* safe-area 값은 스크립트로 바로 읽을 수 없어 `env()` 를 패딩으로 받은 요소의 계산값으로 읽는다. */}
      <div
        ref={reader.safeAreaProbeRef}
        aria-hidden
        className="pointer-events-none invisible absolute top-0 left-0"
        style={{
          padding:
            "env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)",
        }}
      />

      {/* 위치·크기는 잰 값이라 훅이 요소 스타일에 직접 쓴다. */}
      <div ref={reader.scrollerRef} className="absolute touch-pinch-zoom overflow-hidden overscroll-x-none select-none">
        {/* 다단은 블록 요소에 건다 — flex 요소에는 단이 걸리지 않는다. */}
        <article ref={reader.columnsRef} className={typographyClassName}>
          <div className="mb-8 break-inside-avoid">
            <EpisodeHeader novelId={novel.id} novelTitle={novel.title} episodeLabel={episodeLabel} charCount={summary.charCount} />
          </div>

          <div className="flex flex-col gap-4 text-foreground">
            {paragraphs.map((paragraph, index) => (
              // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도
              // 이 순번으로 저장한다).
              <p key={index} data-paragraph-index={index} className="whitespace-pre-line text-pretty break-keep">
                {paragraph}
              </p>
            ))}
          </div>

          {/* 펼침에서 화 끝 블록이 오른쪽 단에 떨어질 때만 켜지는 빈 단 — 화 끝을 새 펼침의 왼쪽 쪽으로 민다. */}
          <div ref={reader.spacerRef} aria-hidden className="hidden break-before-column" />

          {/* 화 끝은 따로 한 화면이다. 한 화면에 이것뿐이라 위에 붙이면 아래가 휑해 세로 가운데에 둔다. */}
          <div ref={reader.endRef} className="flex break-before-column break-inside-avoid flex-col justify-center">
            <EpisodeEnd novelId={novel.id} authorNote={summary.authorNote} next={next} hasDivider={false} onOpenToc={onOpenToc} />
          </div>
        </article>
      </div>
    </main>
  );
}
