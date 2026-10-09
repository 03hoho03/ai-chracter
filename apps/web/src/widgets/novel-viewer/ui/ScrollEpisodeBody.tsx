import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef, type PointerEventHandler } from "react";

import type { ReadingPositionSession } from "../model/useReadingPosition";
import { useScrollReadingTracker } from "../model/useScrollReadingTracker";
import type { ViewerChapter, ViewerEpisode, ViewerNovel, ViewerRoute } from "../model/viewerSource";
import { EpisodeEnd } from "./EpisodeEnd";
import { EpisodeHeader } from "./EpisodeHeader";

type ScrollEpisodeBodyProps = {
  route: ViewerRoute;
  novel: ViewerNovel;
  episode: ViewerEpisode;
  episodeLabel: string;
  next: ViewerChapter | undefined;
  /** 보기 설정(글자 크기·줄 간격)에서 나온 본문 조판 클래스. */
  typographyClassName: string;
  readingPosition: ReadingPositionSession;
  onPointerDown: PointerEventHandler<HTMLElement>;
  onPointerUp: PointerEventHandler<HTMLElement>;
  onOpenToc: (opener: HTMLElement) => void;
};

/** 창 세로 스크롤로 읽는 화 본문. 붙어 있는 동안 읽던 자리로 되돌리고 지금 문단을 잰다(`useScrollReadingTracker`). */
export function ScrollEpisodeBody({
  route,
  novel,
  episode,
  episodeLabel,
  next,
  typographyClassName,
  readingPosition,
  onPointerDown,
  onPointerUp,
  onOpenToc,
}: ScrollEpisodeBodyProps) {
  const { paragraphs } = episode;
  const articleRef = useRef<HTMLElement>(null);

  useScrollReadingTracker({ session: readingPosition, paragraphCount: paragraphs.length, containerRef: articleRef });

  return (
    <main className="min-h-dvh pt-10-safe pb-28" onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
      <article ref={articleRef} className={cn("mx-auto flex max-w-prose flex-col gap-8 px-6", typographyClassName)}>
        <EpisodeHeader
          route={route}
          novelId={novel.id}
          novelTitle={novel.title}
          episodeLabel={episodeLabel}
          isInPageFormat={false}
        />

        <div className="flex flex-col gap-4 text-foreground">
          {paragraphs.map((paragraph, index) => (
            // 문단은 서버가 나눈 순서 그대로이고 이 목록은 다시 정렬되지 않아 순번이 곧 문단의 정체다(읽은 자리도
            // 이 순번으로 저장한다).
            <p key={index} data-paragraph-index={index} className="scroll-mt-4-safe whitespace-pre-line text-pretty break-keep">
              {paragraph}
            </p>
          ))}
        </div>

        <EpisodeEnd
          route={route}
          novelId={novel.id}
          authorNote={episode.authorNote}
          next={next}
          isInPageFormat={false}
          onOpenToc={onOpenToc}
        />
      </article>
    </main>
  );
}
