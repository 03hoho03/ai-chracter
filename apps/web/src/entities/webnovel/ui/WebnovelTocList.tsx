import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";

import { CloverIcon } from "@/entities/clover/@x/webnovel";
import { toEpisodeLabel } from "@/entities/novel/@x/webnovel";

import type { WebnovelChapterItem } from "../api/useWebnovelQuery";

type WebnovelTocListProps = {
  novelId: string;
  chapters: readonly WebnovelChapterItem[];
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

/** 노벨 목차 — 화마다 `N화. 제목`, 읽음 표식, 그리고 오른쪽 끝의 이 사람에게의 가격 표식(무료·소장·클로버 가격).
 * 작품 정보 화면과 읽기 화면의 목차 시트가 같은 목록을 쓴다. 행 하나가 그 화로 가는 링크 하나다 — 잠긴 화도
 * 모달을 바로 열지 않고 그 화 주소로 가서 소장 화면을 지난다(링크와 버튼이 한 목록에 섞이지 않게).
 *
 * 표식은 색 없이 글리프와 글자로 가른다. 유채색은 재화 아이콘의 고정 초록뿐이다(그 그림에만 걸리는 예외). 게시자
 * 본인에게는 가격 표식이 없다 — 언제나 무료로 읽는다. */
export function WebnovelTocList({
  novelId,
  chapters,
  lastReadChapterId,
  currentChapterId,
  surface,
  onNavigate,
}: WebnovelTocListProps) {
  const ordered = [...chapters].sort((a, b) => a.ordinal - b.ordinal);

  return (
    <ol className="flex flex-col">
      {ordered.map((chapter) => {
        const isCurrent = chapter.id === currentChapterId;
        const isFinished = chapter.readingPosition?.finished ?? false;
        const isReading = !isFinished && chapter.id === lastReadChapterId && !isCurrent;
        return (
          <li key={chapter.id}>
            <Link
              to="/webnovels/$novelId/episodes/$chapterId"
              params={{ novelId, chapterId: chapter.id }}
              aria-current={isCurrent ? "page" : undefined}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-3 motion-safe:transition-colors focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px",
                surface === "page" ? "hover:bg-muted" : "hover:bg-secondary",
                isCurrent && "bg-secondary",
              )}
            >
              <span className="min-w-0 flex-1 text-sm font-medium break-keep text-foreground">{toEpisodeLabel(chapter)}</span>
              <ReadingMarker isCurrent={isCurrent} isFinished={isFinished} isReading={isReading} />
              <AccessMarker chapter={chapter} />
            </Link>
          </li>
        );
      })}
    </ol>
  );
}

function ReadingMarker({ isCurrent, isFinished, isReading }: { isCurrent: boolean; isFinished: boolean; isReading: boolean }) {
  if (isCurrent) {
    return <span className="shrink-0 text-xs font-medium whitespace-nowrap text-foreground">지금 화</span>;
  }
  if (isFinished) {
    return (
      <span className="flex shrink-0 items-center text-muted-foreground">
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

/** 이 사람에게 그 화가 어떤가. 폭이 화마다 달라 제목 줄이 흔들리지 않게 오른쪽 끝에 붙인다. */
function AccessMarker({ chapter }: { chapter: WebnovelChapterItem }) {
  switch (chapter.access) {
    case "free":
      return <span className="w-12 shrink-0 text-right text-xs text-muted-foreground">무료</span>;
    case "owned":
      return (
        <span className="flex w-12 shrink-0 justify-end">
          <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium whitespace-nowrap text-muted-foreground">
            소장
          </span>
        </span>
      );
    case "locked":
      return (
        <span className="inline-flex w-12 shrink-0 items-center justify-end gap-1 text-xs text-muted-foreground tabular-nums">
          <CloverIcon />
          <span className="sr-only">소장하려면 클로버</span>
          {chapter.price?.toLocaleString()}
        </span>
      );
    case "publisher":
      return null;
  }
}
