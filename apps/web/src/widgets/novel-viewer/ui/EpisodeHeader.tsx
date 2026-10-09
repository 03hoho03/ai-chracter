import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

type EpisodeHeaderProps = {
  novelId: string;
  novelTitle: string | null;
  episodeLabel: string;
};

/** 화 머리 — 작품 정보로 가는 링크와 화 제목. 글자 수는 화를 다듬을 때 보는 정보라 편집 보드의 화 카드·패널에만
 * 두고, 읽는 화면에는 두지 않는다. */
export function EpisodeHeader({ novelId, novelTitle, episodeLabel }: EpisodeHeaderProps) {
  return (
    <header className="flex flex-col gap-2">
      {/* 바가 숨어 있어도 늘 있는 출구. */}
      <Link
        to="/novels/$novelId"
        params={{ novelId }}
        className="flex w-fit items-center gap-1 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <ChevronLeft aria-hidden className="size-4 shrink-0" />
        <span className="min-w-0 truncate">{novelTitle ?? "제목 미정"}</span>
      </Link>
      <h1 className="text-2xl font-bold tracking-tight text-balance break-keep text-foreground">{episodeLabel}</h1>
    </header>
  );
}
