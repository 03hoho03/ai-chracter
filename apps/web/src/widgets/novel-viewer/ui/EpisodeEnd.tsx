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
  /** 본문 바로 뒤에 이어 붙을 때 위에 구분선을 둔다. 쪽으로 나눠 따로 한 화면에 놓일 때는 쪽 자체가 이미 갈라 둔다. */
  hasDivider: boolean;
  onOpenToc: (opener: HTMLElement) => void;
};

/** 화 끝 — 작가의 말(있을 때만), 다음 화로 가는 버튼, 목차·작품 정보. 바가 숨어 있어도 여기서 다음으로 갈 수 있다.
 * "다음 화"가 이 화면의 유일한 솔리드 채움이다. 마지막 화면 다음 화를 만들 편집 화면으로 가는 길을 둔다.
 *
 * 작가의 말은 지금은 쓴 사람만 보는 메모다(공유 단계에서 독자에게 보일 자리). 여기서는 보여 주기만 하고 고치기는
 * 편집 화면이 맡는다. */
export function EpisodeEnd({ novelId, authorNote, next, hasDivider, onOpenToc }: EpisodeEndProps) {
  const noteHeadingId = useId();

  return (
    <footer className={cn("flex flex-col gap-6", hasDivider && "border-t border-border pt-8")}>
      {authorNote !== "" && (
        <section aria-labelledby={noteHeadingId} className="flex flex-col gap-2 rounded-xl border border-border p-4">
          <h2 id={noteHeadingId} className="text-xs font-medium text-muted-foreground">
            작가의 말 · 나만 보여요
          </h2>
          <p className="text-sm whitespace-pre-line text-pretty break-keep text-foreground">{authorNote}</p>
        </section>
      )}

      {next === undefined ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm break-keep text-muted-foreground">마지막 화예요.</p>
          <Button asChild variant="outline">
            <Link to="/novels/$novelId/board" params={{ novelId }}>
              편집에서 다음 화 만들기
            </Link>
          </Button>
        </div>
      ) : (
        <Button asChild className="w-full">
          <Link to="/novels/$novelId/episodes/$chapterId" params={{ novelId, chapterId: next.id }}>
            <span className="min-w-0 truncate">다음 화 · {toEpisodeLabel(next)}</span>
            <ChevronRight aria-hidden />
          </Link>
        </Button>
      )}

      <div className="flex flex-wrap justify-center gap-2">
        <Button type="button" variant="ghost" onClick={(event) => onOpenToc(event.currentTarget)}>
          목차
        </Button>
        <Button asChild variant="ghost">
          <Link to="/novels/$novelId" params={{ novelId }}>
            작품 정보
          </Link>
        </Button>
      </div>
    </footer>
  );
}
