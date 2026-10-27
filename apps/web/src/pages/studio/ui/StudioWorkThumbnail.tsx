import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen, BookText, UserRound } from "lucide-react";

import type { WorkItem } from "@/entities/work";

import { toStudioThumbnailUrl } from "../model/studioWorkRow";

const FALLBACK_ICON = { character: UserRound, story: BookOpen, novel: BookText } as const;

/** 정사각 썸네일. 캐릭터 1:1·스토리 2:3·소설 표지를 같은 상자로 잘라 행의 열을 맞춘다. 그림이 없으면 같은 상자에
 * 유형 아이콘을 둔다. 장식이라 대체 글은 비운다 — 이름은 바로 옆 제목이 말한다. */
export function StudioWorkThumbnail({ item, className }: { item: WorkItem; className?: string }) {
  const url = toStudioThumbnailUrl(item);
  const FallbackIcon = FALLBACK_ICON[item.kind];

  return (
    <span className={cn("flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-secondary", className)}>
      {url ? (
        <img src={url} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
      ) : (
        <FallbackIcon aria-hidden className="size-5 text-muted-foreground" />
      )}
    </span>
  );
}
