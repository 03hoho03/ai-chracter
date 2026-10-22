import { cn } from "@ai-character-chat/ui/lib/utils";
import { useRef, type PointerEventHandler, type ReactNode } from "react";

import { toReaderBlocks } from "@/entities/novel";

import type { ReadingPositionSession } from "../model/useReadingPosition";
import { useScrollReadingTracker } from "../model/useScrollReadingTracker";
import type { EpisodeEndExtras, ViewerChapter, ViewerEpisode, ViewerNovel, ViewerRoute } from "../model/viewerSource";
import { ScrollEpisodeBlocks } from "./EpisodeBlocks";
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
  endExtras?: EpisodeEndExtras;
  /** 화 제목 아래 한 줄. */
  headerNote?: ReactNode;
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
  endExtras,
  headerNote,
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
          note={headerNote}
        />

        <ScrollEpisodeBlocks paragraphs={paragraphs} blocks={toReaderBlocks(paragraphs.length, episode.illustrations)} />

        <EpisodeEnd
          route={route}
          novelId={novel.id}
          authorNote={episode.authorNote}
          next={next}
          isInPageFormat={false}
          onOpenToc={onOpenToc}
          extras={endExtras}
        />
      </article>
    </main>
  );
}
