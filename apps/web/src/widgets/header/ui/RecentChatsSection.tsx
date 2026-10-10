import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronRight, ImageOff } from "lucide-react";
import { useId } from "react";

import { useRecentChatRoomListQuery, type MyChatRoomListItem } from "@/entities/chat-room";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

import { loginRedirectTarget } from "../lib/loginRedirectTarget";
import { SIDE_PANEL_ROW_CLASS } from "./sidePanelRowClass";

/** 이 섹션이 놓이는 표면. `muted` 는 `popover`(드로어)와 같은 값이라 거기서는 썸네일 웰·스켈레톤이 사라진다 — 표면마다
 * 채움을 고른다(DESIGN.md Colors 절 표면 위 채움). */
type RecentChatsSurface = "background" | "popover";

const WELL_CLASS: Record<RecentChatsSurface, string> = {
  background: "bg-muted",
  popover: "bg-secondary",
};

const SKELETON_ROW_KEYS = [0, 1, 2, 3, 4];

type RecentChatsSectionProps = {
  /** 로그인한 사용자 id. 없으면 비로그인 안내를 그린다. */
  viewerId: string | undefined;
  /** 세션을 아직 묻는 중이면 비로그인으로 단정하지 않고 스켈레톤을 둔다. */
  isSessionPending: boolean;
  surface: RecentChatsSurface;
};

/**
 * "최근 대화" 섹션 — 최근 활동순 내 대화방 앞 10개와 전체 목록(`/chats`)으로 가는 "전체 보기". 데스크톱에서 어제 대화로
 * 한 번에 돌아가는 길이다.
 *
 * 섹션 이름은 제목 요소가 아니라 문단이다 — 패널은 DOM 에서 본문 앞이라 h2 를 쓰면 페이지 h1 보다 먼저 나온다. 목록이
 * `aria-labelledby` 로 이 이름을 가리킨다. "전체 보기"는 목록 끝이 아니라 머리에 둔다 — 낮은 화면에서는 목록 끝이 패널
 * 스크롤 아래로 가서 거기 두면 스크롤해야 닿는다.
 */
export function RecentChatsSection({ viewerId, isSessionPending, surface }: RecentChatsSectionProps) {
  const labelId = useId();
  const isSignedOut = !isSessionPending && viewerId === undefined;

  return (
    <section aria-labelledby={labelId} className="mt-4">
      <div className="flex h-8 items-center justify-between pr-2 pl-4">
        <p id={labelId} className="text-xs font-medium text-muted-foreground">
          최근 대화
        </p>
        {!isSignedOut && (
          <Link
            to="/chats"
            className="inline-flex items-center gap-0.5 rounded-md px-1 text-xs text-muted-foreground motion-safe:transition-colors hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring"
          >
            {/* 접근 이름은 보이는 글자를 포함해야 해서 앞에 숨은 글자를 덧붙인다 — "최근 대화 전체 보기". */}
            <span className="sr-only">최근 대화 </span>전체 보기
            <ChevronRight aria-hidden className="size-3.5" />
          </Link>
        )}
      </div>

      {isSignedOut ? (
        <SignedOutNotice />
      ) : (
        <RecentChatsBody viewerId={viewerId} labelId={labelId} surface={surface} />
      )}
    </section>
  );
}

/** 대화 목록 자리의 로그인 안내. 버튼이 `outline` 인 이유: 비로그인 헤더의 "로그인"이 그 화면의 솔리드 버튼이다. 라벨을
 * "로그인하고 보기"로 둔 것도 헤더의 "로그인"과 라벨로 가르기 위해서다(같은 목적지 진입점이 한 화면에 둘이다). outline 의
 * hover 채움 `muted` 는 이 표면에서 보이지 않아 `secondary` 로 덮는다. */
function SignedOutNotice() {
  const location = useRouterState({ select: (state) => state.location });
  const redirect = loginRedirectTarget(location);

  return (
    <div className="flex flex-col items-start gap-2 px-4 py-1">
      <p className="text-sm break-keep text-muted-foreground">로그인하면 이어서 하던 대화가 여기에 보여요.</p>
      <Button asChild variant="outline" size="sm" className="hover:bg-secondary">
        <Link to="/login" search={{ redirect }}>
          로그인하고 보기
        </Link>
      </Button>
    </div>
  );
}

type RecentChatsBodyProps = {
  viewerId: string | undefined;
  labelId: string;
  surface: RecentChatsSurface;
};

/** 데이터가 있는 채 다시 받기에 실패하면 목록을 그대로 둔다 — 실패 배너는 `/chats` 가 진다. 목록이 없을 때만 다시 시도를
 * 준다. */
function RecentChatsBody({ viewerId, labelId, surface }: RecentChatsBodyProps) {
  const listQuery = useRecentChatRoomListQuery(viewerId);

  if (listQuery.isPending) return <RecentChatsSkeleton surface={surface} />;

  const items = listQuery.data ?? [];

  if (listQuery.isError && items.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2 px-4 py-1">
        <p className="text-sm break-keep text-muted-foreground">최근 대화를 불러오지 못했어요.</p>
        <Button type="button" variant="outline" size="sm" className="hover:bg-secondary" onClick={() => void listQuery.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  // 버튼을 두지 않는다 — 이 섹션은 모든 화면에 늘 있어서, 홈으로 가는 버튼을 두면 내비의 "홈"과 같은 진입점이 하나 더 생긴다.
  if (items.length === 0) {
    return (
      <p className="px-4 py-1 text-sm break-keep text-muted-foreground">
        아직 시작한 대화가 없어요. 마음에 드는 작품에서 대화를 시작해 보세요.
      </p>
    );
  }

  return (
    <ul aria-labelledby={labelId} className="flex flex-col gap-0.5">
      {items.map((item) => (
        <li key={item.id}>
          <RecentChatRow item={item} surface={surface} />
        </li>
      ))}
    </ul>
  );
}

/** 스켈레톤은 진행 표시라 `animate-pulse` 를 모션 가드하지 않는다(DESIGN.md Motion 절). 모양은 행과 같다. */
function RecentChatsSkeleton({ surface }: { surface: RecentChatsSurface }) {
  const fillClass = cn("animate-pulse", WELL_CLASS[surface]);

  return (
    <div aria-hidden className="flex flex-col gap-0.5">
      {SKELETON_ROW_KEYS.map((key) => (
        <div key={key} className="flex min-h-12 items-center gap-3 px-4 py-1">
          <div className={cn("size-8 shrink-0 rounded-md", fillClass)} />
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div className={cn("h-3.5 w-4/5 rounded-sm", fillClass)} />
            <div className={cn("h-3 w-1/2 rounded-sm", fillClass)} />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * 한 방의 행: 썸네일 · 작품명 · "방 이름 · 상대 시각". 같은 작품의 방이 여럿이면 썸네일과 작품명이 같아 방 이름과 시각이
 * 가른다. 미리보기 문장은 넣지 않는다 — 세 줄째를 넣으면 열 개가 낮은 화면에서 내비까지 밀어 올린다. 행 메뉴도 두지 않는다
 * (행마다 Tab 정지가 하나씩 는다).
 *
 * 썸네일 테두리(`foreground/10`)는 웰 색과 무관하게 경계를 남긴다 — 드로어에서는 웰과 hover 채움이 같은 `secondary` 라
 * 테두리가 없으면 그 순간 썸네일 자리가 사라진다. 현재 방의 굵기는 첫 줄(작품명)에만 건다 — 행 전체에 걸면 둘째 줄까지
 * 굵어져 두 줄을 가르는 굵기 차이가 무너진다.
 */
function RecentChatRow({ item, surface }: { item: MyChatRoomListItem; surface: RecentChatsSurface }) {
  const relativeTime = formatRelativeTime(item.lastMessageAt ?? item.createdAt, new Date());

  return (
    <Link
      to="/chat/$roomId"
      params={{ roomId: item.id }}
      className={cn(SIDE_PANEL_ROW_CLASS, "group min-h-12 px-4 py-1")}
    >
      <span className={cn("size-8 shrink-0 overflow-hidden rounded-md border border-foreground/10", WELL_CLASS[surface])}>
        {item.thumbnailUrl ? (
          <img src={item.thumbnailUrl} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
        ) : (
          <span className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden className="size-3.5" />
          </span>
        )}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate leading-5 group-aria-[current=page]:font-semibold">{item.contentName}</span>
        <span className="flex min-w-0 gap-1 text-xs leading-5 font-normal">
          <span className="truncate">{item.name}</span>{" "}
          <span aria-hidden>·</span>{" "}
          <span className="shrink-0">{relativeTime}</span>
        </span>
      </span>
    </Link>
  );
}
