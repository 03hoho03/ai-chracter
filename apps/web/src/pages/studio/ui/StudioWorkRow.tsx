import { ChevronRight } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { useId } from "react";

import type { WorkItem } from "@/entities/work";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

import { toStudioNextAction, toStudioStatusBadges, toStudioWorkTitle } from "../model/studioWorkRow";
import { StudioStatusBadges, StudioTypeBadge } from "./StudioBadges";
import { toStudioLinkProps } from "./studioRowLink";
import { StudioWorkRowMenu } from "./StudioWorkRowMenu";
import { StudioWorkThumbnail } from "./StudioWorkThumbnail";

/** 넓은 목록(컨테이너 `@3xl` 이상)의 열. 열 머리와 행이 같은 값을 써야 열이 맞는다 — 작품 · 상태 · 마지막 수정 · 다음 행동. */
export const STUDIO_ROW_COLUMNS = "@3xl:grid-cols-[minmax(0,1fr)_13rem_6rem_7rem]";

type StudioWorkRowProps = {
  item: WorkItem;
  userId: string;
  onRemoved: () => void;
  /** 묶음 화면에서만 — 행 메뉴의 "이 묶음에서 빼기". */
  onRemoveFromBundle?: () => void;
};

/**
 * 작품 한 줄. 행 전체가 다음 행동으로 가는 링크 하나이고, "⋯" 메뉴만 따로 초점을 받는다 — 같은 목적지에 탭 정지를 둘
 * 만들지 않는다. 링크 안에 메뉴 버튼을 넣을 수 없어(대화형 요소 중첩) 상자는 바깥 `div` 가 그리고 링크는 `after:` 로 상자
 * 전체를 덮는다(내 소설 목록 행과 같은 꼴). hover 는 페이지 배경 위라 `bg-muted` 다 — `secondary` 는 라이트에서 흐린 메타
 * 글자의 대비를 AA 아래로 떨어뜨리고, `bg-muted` 가 사라지는 건 카드·팝오버 위에서다.
 *
 * 링크 이름은 "제목 — 다음 행동"이고, 유형·상태·마지막 수정은 설명으로 붙인다(`aria-describedby`).
 *
 * 좁은 폭은 [썸네일 · 제목 / 배지 줄 / "n 전 수정 · 다음 행동"] 한 열, 넓은 폭은 열 머리와 맞춘 네 열이다. 두 꼴을 같은
 * 요소로 그리려고 묶음 상자는 넓은 폭에서 `contents` 로 풀려 안의 조각이 바로 격자 칸이 된다.
 */
export function StudioWorkRow({ item, userId, onRemoved, onRemoveFromBundle }: StudioWorkRowProps) {
  const descriptionId = useId();
  const title = toStudioWorkTitle(item);
  const action = toStudioNextAction(item);
  const badges = toStudioStatusBadges(item);
  const editedLabel = formatRelativeTime(item.editedAt, new Date());

  return (
    <div className="relative flex items-start gap-1 rounded-xl px-2 py-2 motion-safe:transition-colors has-[a:hover]:bg-muted has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-ring/50 has-[a:active]:translate-y-px @3xl:items-center">
      <Link
        {...toStudioLinkProps(action.target)}
        aria-label={`${title} — ${action.label}`}
        aria-describedby={descriptionId}
        className="flex min-w-0 flex-1 items-start gap-3 outline-none after:absolute after:inset-0 after:rounded-xl @3xl:items-center"
      >
        <StudioWorkThumbnail item={item} className="size-12 @3xl:size-14" />

        <span className={`grid min-w-0 flex-1 gap-1 @3xl:grid-rows-[auto_auto] @3xl:items-center @3xl:gap-x-4 ${STUDIO_ROW_COLUMNS}`}>
          <span className="text-sm font-semibold break-keep text-foreground [overflow-wrap:anywhere] @3xl:col-start-1 @3xl:row-start-1">
            {title}
          </span>

          <span id={descriptionId} className="contents">
            <span className="flex flex-wrap items-center gap-1.5 @3xl:contents">
              <span className="flex items-center gap-1.5 @3xl:col-start-1 @3xl:row-start-2">
                <StudioTypeBadge kind={item.kind} />
                {item.kind === "novel" && (
                  <span className="text-xs text-muted-foreground">
                    {item.chapterCount > 0 ? `${item.chapterCount}화` : "아직 화가 없어요"}
                  </span>
                )}
              </span>
              <StudioStatusBadges badges={badges} className="@3xl:col-start-2 @3xl:row-span-2 @3xl:row-start-1" />
              {badges.length === 0 && (
                <span aria-hidden className="hidden text-sm text-muted-foreground @3xl:col-start-2 @3xl:row-span-2 @3xl:row-start-1 @3xl:block">
                  —
                </span>
              )}
            </span>

            <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground @3xl:contents">
              <time dateTime={item.editedAt} className="@3xl:col-start-3 @3xl:row-span-2 @3xl:row-start-1 @3xl:text-sm">
                {editedLabel}
                <span className="@3xl:sr-only"> 수정</span>
              </time>
              <span aria-hidden className="@3xl:hidden">
                ·
              </span>
              {/* 다음 행동 글자는 링크 이름에 이미 있으므로 읽지 않는다. 좁은 폭에선 메타 줄 끝, 넓은 폭에선 마지막 열이다. */}
              <span
                aria-hidden
                className="inline-flex items-center gap-0.5 font-semibold text-foreground @3xl:col-start-4 @3xl:row-span-2 @3xl:row-start-1 @3xl:text-sm"
              >
                {action.label}
                <ChevronRight className="size-3.5 text-muted-foreground" />
              </span>
            </span>
          </span>
        </span>
      </Link>

      <div className="relative">
        <StudioWorkRowMenu
          item={item}
          title={title}
          userId={userId}
          onRemoved={onRemoved}
          onRemoveFromBundle={onRemoveFromBundle}
        />
      </div>
    </div>
  );
}
