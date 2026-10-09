import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

type EpisodeHeaderProps = {
  novelId: string;
  novelTitle: string | null;
  episodeLabel: string;
  /** 페이지 모드 판형 안에 놓이는가. 그러면 크기를 rem 대신 px 로 고정한다 — 판형 안이 브라우저 기본 글자 크기를 따라
   * 커지면 같은 판형인데 첫 쪽에 담기는 글이 달라져 쪽 수가 바뀐다. */
  isInPageFormat: boolean;
};

/** 화 머리 — 작품 정보로 가는 링크와 화 제목. 글자 수는 화를 다듬을 때 보는 정보라 편집 보드의 화 카드·패널에만
 * 두고, 읽는 화면에는 두지 않는다. */
export function EpisodeHeader({ novelId, novelTitle, episodeLabel, isInPageFormat }: EpisodeHeaderProps) {
  return (
    <header className={cn("flex flex-col", isInPageFormat ? "gap-[8px]" : "gap-2")}>
      {/* 바가 숨어 있어도 늘 있는 출구. */}
      <Link
        to="/novels/$novelId"
        params={{ novelId }}
        className={cn(
          "flex w-fit items-center gap-1 rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          isInPageFormat ? "text-[14px]/[20px]" : "text-sm",
        )}
      >
        <ChevronLeft aria-hidden className={cn("shrink-0", isInPageFormat ? "size-[16px]" : "size-4")} />
        <span className="min-w-0 truncate">{novelTitle ?? "제목 미정"}</span>
      </Link>
      <h1
        className={cn(
          "font-bold tracking-tight text-balance break-keep text-foreground",
          isInPageFormat ? "text-[24px]/[32px]" : "text-2xl",
        )}
      >
        {episodeLabel}
      </h1>
    </header>
  );
}
