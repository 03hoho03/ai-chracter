import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

type EpisodeHeaderProps = {
  novelId: string;
  novelTitle: string | null;
  episodeLabel: string;
  charCount: number;
};

/** 화 머리 — 작품 정보로 가는 링크, 화 제목, 글자 수. */
export function EpisodeHeader({ novelId, novelTitle, episodeLabel, charCount }: EpisodeHeaderProps) {
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
      <p className="text-xs text-muted-foreground tabular-nums">{charCount.toLocaleString()}자</p>
    </header>
  );
}
