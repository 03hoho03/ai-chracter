import { cn } from "@ai-character-chat/ui/lib/utils";
import { BookOpen, BookText, UserRound, type LucideIcon } from "lucide-react";

import type { WorkItem } from "@/entities/work";

import type { StudioStatusBadge } from "../model/studioWorkRow";

const BADGE_CLASS = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-badge font-medium whitespace-nowrap";

const TYPE_BADGE: Record<WorkItem["kind"], { label: string; Icon: LucideIcon }> = {
  character: { label: "캐릭터", Icon: UserRound },
  story: { label: "스토리", Icon: BookOpen },
  novel: { label: "소설", Icon: BookText },
};

/** 유형은 채움 + 아이콘, 상태는 윤곽 — 형태로 위계가 갈린다(DESIGN.md Status badges 절). */
export function StudioTypeBadge({ kind }: { kind: WorkItem["kind"] }) {
  const { label, Icon } = TYPE_BADGE[kind];

  return (
    <span className={cn(BADGE_CLASS, "bg-secondary text-secondary-foreground")}>
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}

export const STUDIO_STATUS_BADGE_LABEL: Record<StudioStatusBadge, string> = {
  draft: "초안",
  public: "공개 중",
  published: "발행됨",
  changed: "수정본 있음",
  restricted: "이용제한",
  withdrawn: "공개 거둠",
  inReview: "심사 대기",
  rejected: "반려",
  hiddenFromReaders: "독자에게 안 보임",
};

/** 중립 상태는 윤곽 + 흐린 잉크이고, 사용자가 손대거나 읽을 것이 생긴 상태(고친 내용이 공개를 기다림·반려)만 잉크를
 * 밝기 천장으로 올린다. 이용제한만 유일하게 `destructive` 틴트다 — 색만으로 말하지 않도록 글자가 늘 함께 있다. */
const STATUS_BADGE_CLASS: Record<StudioStatusBadge, string> = {
  draft: "border border-border text-muted-foreground",
  public: "border border-border text-muted-foreground",
  published: "border border-border text-muted-foreground",
  changed: "border border-border text-foreground",
  restricted: "bg-destructive/10 text-destructive-text",
  withdrawn: "border border-border text-muted-foreground",
  inReview: "border border-border text-muted-foreground",
  rejected: "border border-border text-foreground",
  hiddenFromReaders: "border border-border text-muted-foreground",
};

export function StudioStatusBadges({ badges, className }: { badges: StudioStatusBadge[]; className?: string }) {
  if (badges.length === 0) return null;

  return (
    <span className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {badges.map((badge) => (
        <span key={badge} className={cn(BADGE_CLASS, STATUS_BADGE_CLASS[badge])}>
          {STUDIO_STATUS_BADGE_LABEL[badge]}
        </span>
      ))}
    </span>
  );
}
