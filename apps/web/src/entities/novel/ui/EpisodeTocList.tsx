import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";

import type { NovelChapterSummary } from "../api/useNovelQuery";
import { toEpisodeLabel } from "../model/episodeLabel";

type EpisodeTocListProps = {
  novelId: string;
  chapters: readonly NovelChapterSummary[];
  /** 마지막으로 읽던 화. 다 읽지 않았으면 "읽는 중" 표식을 단다. */
  lastReadChapterId: string | undefined;
  /** 지금 읽고 있는 화(읽기 화면의 목차에서만). `aria-current` 와 "지금 화" 글자로 알린다. */
  currentChapterId?: string;
  /** 목록이 놓인 표면. 페이지 위에서는 hover 가 `muted`, 시트(`popover`) 위에서는 `muted` 가 표면과 같은 값이라
   * 사라지므로 `secondary` 다(DESIGN.md Colors 절 "표면 위 채움"). */
  surface: "page" | "sheet";
  /** 항목을 누른 순간(시트를 닫는 데 쓴다). */
  onNavigate?: () => void;
};

/** 목차 — 화마다 `N화. 제목`, 요약 두 줄, 읽음 표식. 작품 정보 화면과 읽기 화면의 목차 시트가 같은 목록을 쓴다.
 * 행 하나가 그 화로 가는 링크 하나다. 표식은 색 없이 글리프와 글자로만 가른다(읽음은 상태라 강조색을 쓰지 않는다). */
export function EpisodeTocList({
  novelId,
  chapters,
  lastReadChapterId,
  currentChapterId,
  surface,
  onNavigate,
}: EpisodeTocListProps) {
  const ordered = [...chapters].sort((a, b) => a.ordinal - b.ordinal);

  return (
    <ol className="flex flex-col">
      {ordered.map((chapter) => {
        const isCurrent = chapter.id === currentChapterId;
        const isReading = !chapter.finishedReading && chapter.id === lastReadChapterId && !isCurrent;
        return (
          <li key={chapter.id}>
            <Link
              to="/novels/$novelId/episodes/$chapterId"
              params={{ novelId, chapterId: chapter.id }}
              aria-current={isCurrent ? "page" : undefined}
              onClick={onNavigate}
              className={cn(
                "flex items-start gap-3 rounded-lg px-3 py-3 motion-safe:transition-colors focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px",
                surface === "page" ? "hover:bg-muted" : "hover:bg-secondary",
                isCurrent && "bg-secondary",
              )}
            >
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="text-sm font-medium break-keep text-foreground">{toEpisodeLabel(chapter)}</span>
                {chapter.summary !== null && chapter.summary !== "" && (
                  <span className="line-clamp-2 text-xs break-keep text-muted-foreground">{chapter.summary}</span>
                )}
              </span>
              <EpisodeMarker isCurrent={isCurrent} isFinished={chapter.finishedReading} isReading={isReading} />
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

function EpisodeMarker({ isCurrent, isFinished, isReading }: { isCurrent: boolean; isFinished: boolean; isReading: boolean }) {
  if (isCurrent) {
    return <span className="shrink-0 pt-0.5 text-xs font-medium whitespace-nowrap text-foreground">지금 화</span>;
  }
  if (isFinished) {
    return (
      <span className="flex shrink-0 items-center pt-0.5 text-muted-foreground">
        <Check aria-hidden className="size-4" />
        <span className="sr-only">다 읽음</span>
      </span>
    );
  }
  if (isReading) {
    return (
      <span className="inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium whitespace-nowrap text-muted-foreground">
        읽는 중
      </span>
    );
  }
  return null;
}
