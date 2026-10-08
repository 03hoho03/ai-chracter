import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef, type PointerEventHandler } from "react";

import type { NovelChapterSummary, NovelDetailResponse } from "@/entities/novel";

import type { ReadingPositionSession } from "../model/useReadingPosition";
import { useScrollReadingTracker } from "../model/useScrollReadingTracker";
import { EpisodeEnd } from "./EpisodeEnd";
import { EpisodeHeader } from "./EpisodeHeader";
import { PreviousSummary } from "./PreviousSummary";

type ScrollEpisodeBodyProps = {
  novel: NovelDetailResponse;
  summary: NovelChapterSummary;
  episodeLabel: string;
  paragraphs: readonly string[];
  previous: NovelChapterSummary | undefined;
  next: NovelChapterSummary | undefined;
  /** 보기 설정(글자 크기·줄 간격·여백)에서 나온 본문 조판 클래스. */
  typographyClassName: string;
  readingPosition: ReadingPositionSession;
  onPointerDown: PointerEventHandler<HTMLElement>;
  onPointerUp: PointerEventHandler<HTMLElement>;
  onOpenToc: (opener: HTMLElement) => void;
};

/** 창 세로 스크롤로 읽는 화 본문. 붙어 있는 동안 읽던 자리로 되돌리고 지금 문단을 잰다(`useScrollReadingTracker`). */
export function ScrollEpisodeBody({
  novel,
  summary,
  episodeLabel,
  paragraphs,
  previous,
  next,
  typographyClassName,
  readingPosition,
  onPointerDown,
  onPointerUp,
  onOpenToc,
}: ScrollEpisodeBodyProps) {
  const articleRef = useRef<HTMLElement>(null);

  useScrollReadingTracker({ session: readingPosition, paragraphCount: paragraphs.length, containerRef: articleRef });

  return (
    <main className="min-h-dvh pt-10-safe pb-28" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
      <article ref={articleRef} className={cn("mx-auto flex max-w-prose flex-col gap-8", typographyClassName)}>
        <EpisodeHeader novelId={novel.id} novelTitle={novel.title} episodeLabel={episodeLabel} charCount={summary.charCount} />

        {previous !== undefined && previous.summary !== null && previous.summary !== "" && (
          <PreviousSummary ordinal={previous.ordinal} summary={previous.summary} />
        )}

        <div className="flex flex-col gap-4 text-foreground">
          {paragraphs.map((paragraph, index) => (
            // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도
            // 이 순번으로 저장한다).
            <p key={index} data-paragraph-index={index} className="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep">
              {paragraph}
            </p>
          ))}
        </div>

        <EpisodeEnd novelId={novel.id} authorNote={summary.authorNote} next={next} hasDivider onOpenToc={onOpenToc} />
      </article>
    </main>
  );
}
