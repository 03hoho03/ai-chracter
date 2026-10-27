import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";

import type { WorkItem } from "@/entities/work";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

import { toStudioNextAction, toStudioStatusBadges, toStudioWorkTitle } from "../model/studioWorkRow";
import { StudioStatusBadges, StudioTypeBadge } from "./StudioBadges";
import { toStudioLinkProps } from "./studioRowLink";
import { StudioWorkThumbnail } from "./StudioWorkThumbnail";

/**
 * 이어 만들기 카드 — 가장 최근에 손댄 끝나지 않은 일 하나. 카드 면(`bg-card`) 위라 hover 를 따로 두지 않고, 할 일은 이
 * 화면의 유일한 솔리드 채움인 `primary` 버튼 하나가 진다. 같은 작품은 아래 목록에도 그대로 있다(목록이 전체의 기준이라
 * 빼면 필터 건수와 어긋난다).
 */
export function StudioContinueCard({ item }: { item: WorkItem }) {
  const title = toStudioWorkTitle(item);
  const action = toStudioNextAction(item);
  // 한 줄 사유는 수정본이 공개를 기다릴 때만 단다 — 초안·소설은 할 일이 버튼 이름에 이미 드러난다.
  const reason = action.label === "공개 준비" ? "편집한 내용은 공개해야 독자에게 보여요" : undefined;

  return (
    <div className="flex flex-col gap-4 rounded-xl bg-card p-4 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3 sm:items-center">
        <StudioWorkThumbnail item={item} className="size-18" />
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className="text-base font-semibold break-keep text-card-foreground [overflow-wrap:anywhere]">{title}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <StudioTypeBadge kind={item.kind} />
            <StudioStatusBadges badges={toStudioStatusBadges(item)} />
          </div>
          <p className="text-xs break-keep text-muted-foreground">
            <time dateTime={item.editedAt}>{formatRelativeTime(item.editedAt, new Date())} 수정</time>
            {reason && ` · ${reason}`}
          </p>
        </div>
      </div>
      <Button asChild className="w-full shrink-0 sm:w-auto">
        <Link {...toStudioLinkProps(action.target)} aria-label={`${title} ${action.label}`}>
          {action.label}
        </Link>
      </Button>
    </div>
  );
}

/** 이어 만들기 자리의 로딩 자리표시. 카드와 높이가 같아 목록이 도착할 때 아래가 밀리지 않는다. */
export function StudioContinueCardSkeleton() {
  return (
    <div aria-hidden className="flex items-center gap-3 rounded-xl bg-card p-4">
      <span className="size-18 shrink-0 animate-pulse rounded-lg bg-secondary" />
      <span className="flex flex-1 flex-col gap-2">
        <span className="h-5 w-2/5 animate-pulse rounded bg-secondary" />
        <span className="h-4 w-1/4 animate-pulse rounded bg-secondary" />
      </span>
    </div>
  );
}
