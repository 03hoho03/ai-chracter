import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useId } from "react";

import { toEpisodeLabel, type NovelChapterSummary } from "@/entities/novel";

type EpisodeEndProps = {
  novelId: string;
  authorNote: string;
  next: NovelChapterSummary | undefined;
  /** 페이지 모드 판형 안에 따로 한 쪽으로 놓이는가(스크롤 모드는 본문 바로 뒤에 이어 붙는다). 판형 안이면 위 구분선
   * 없이 — 쪽 자체가 이미 갈라 둔다 — 크기를 px 로 고정한다. 판형 안이 브라우저 기본 글자 크기를 따라 커지면 이
   * 블록이 한 쪽을 넘쳐 같은 판형인데 쪽 수가 바뀐다. */
  isInPageFormat: boolean;
  onOpenToc: (opener: HTMLElement) => void;
};

/** 판형 안에서 버튼 크기를 정하는 값들 — 기본 버튼(36px·글자 16px·아이콘 16px)과 같은 모양을 px 로 적었다. 아이콘은
 * 크기 클래스를 직접 받아야 버튼 기본의 rem 아이콘 크기가 걸리지 않는다. */
const PAGE_FORMAT_BUTTON = "h-[36px] gap-[6px] px-[16px] text-[16px]";
const PAGE_FORMAT_ICON = "size-[16px]";

/** 화 끝 — 작가의 말(있을 때만), 다음 화로 가는 버튼, 목차·작품 정보. 바가 숨어 있어도 여기서 다음으로 갈 수 있다.
 * "다음 화"가 이 화면의 유일한 솔리드 채움이다. 마지막 화면 다음 화를 만들 편집 화면으로 가는 길을 둔다.
 *
 * 작가의 말은 지금은 쓴 사람만 보는 메모다(공유 단계에서 독자에게 보일 자리). 여기서는 보여 주기만 하고 고치기는
 * 편집 화면이 맡는다. */
export function EpisodeEnd({ novelId, authorNote, next, isInPageFormat, onOpenToc }: EpisodeEndProps) {
  const noteHeadingId = useId();
  const button = isInPageFormat ? PAGE_FORMAT_BUTTON : undefined;
  const icon = isInPageFormat ? PAGE_FORMAT_ICON : undefined;

  return (
    <footer className={cn("flex flex-col", isInPageFormat ? "gap-[24px]" : "gap-6 border-t border-border pt-8")}>
      {authorNote !== "" && (
        <section
          aria-labelledby={noteHeadingId}
          className={cn("flex flex-col rounded-xl border border-border", isInPageFormat ? "gap-[8px] p-[16px]" : "gap-2 p-4")}
        >
          <h2
            id={noteHeadingId}
            className={cn("font-medium text-muted-foreground", isInPageFormat ? "text-[14px]/[20px]" : "text-xs")}
          >
            작가의 말 · 나만 보여요
          </h2>
          <p
            className={cn(
              "whitespace-pre-line text-pretty break-keep text-foreground",
              isInPageFormat ? "text-[16px]/[24px]" : "text-sm",
            )}
          >
            {authorNote}
          </p>
        </section>
      )}

      {next === undefined ? (
        <div className={cn("flex flex-col items-start", isInPageFormat ? "gap-[12px]" : "gap-3")}>
          <p className={cn("break-keep text-muted-foreground", isInPageFormat ? "text-[16px]/[24px]" : "text-sm")}>
            마지막 화예요.
          </p>
          <Button asChild variant="outline" className={button}>
            <Link to="/novels/$novelId/board" params={{ novelId }}>
              편집에서 다음 화 만들기
            </Link>
          </Button>
        </div>
      ) : (
        <Button asChild className={cn("w-full", button)}>
          <Link to="/novels/$novelId/episodes/$chapterId" params={{ novelId, chapterId: next.id }}>
            <span className="min-w-0 truncate">다음 화 · {toEpisodeLabel(next)}</span>
            <ChevronRight aria-hidden className={icon} />
          </Link>
        </Button>
      )}

      <div className={cn("flex flex-wrap justify-center", isInPageFormat ? "gap-[8px]" : "gap-2")}>
        <Button type="button" variant="ghost" className={button} onClick={(event) => onOpenToc(event.currentTarget)}>
          목차
        </Button>
        <Button asChild variant="ghost" className={button}>
          <Link to="/novels/$novelId" params={{ novelId }}>
            작품 정보
          </Link>
        </Button>
      </div>
    </footer>
  );
}
