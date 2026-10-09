import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";

import type { WebnovelSource } from "../api/useWebnovelListQuery";

/** 원작 표기 — `원작 · 작품명 · 캐릭터명`(스토리는 캐릭터명이 없다). 작품명은 소설을 만들 때의 원작 사본이다.
 * `isLinked` 이고 원작을 지금 볼 수 있을 때만 작품명이 원작 상세로 가는 링크다(목록 행처럼 줄 전체가 이미 링크인
 * 자리는 글자만 — 링크 안에 링크를 둘 수 없다). */
export function WebnovelSourceCredit({
  source,
  isLinked,
  className,
}: {
  source: WebnovelSource;
  isLinked: boolean;
  className?: string;
}) {
  return (
    <p className={cn("min-w-0 break-keep text-muted-foreground", className)}>
      원작 ·{" "}
      {isLinked && source.linkable ? (
        <Link
          to="/content/$type/$id"
          params={{ type: source.contentType, id: source.contentId }}
          className="rounded-sm text-foreground hover:underline focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {source.title}
        </Link>
      ) : (
        source.title
      )}
      {source.characterName !== null && ` · ${source.characterName}`}
    </p>
  );
}
