import { useId, useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useRouter } from "@tanstack/react-router";
import { ChevronLeft, ImageOff } from "lucide-react";
import { toast } from "sonner";

import { stripChatNotation } from "@/entities/chat-room";
import { useCloverPricingQuery } from "@/entities/clover";
import { ContentListEmptyState, ContentListLoadMore } from "@/entities/content";
import { isLegalReconsentRequiredError } from "@/entities/legal";
import {
  isContentNovelizeForbiddenError,
  isNovelizeNotAllowedError,
  novelKeys,
  toNovelizeForbiddenCopy,
  useEnsureRoomNovelMutation,
  useNovelSourcesQuery,
  type NovelSourceRoom,
} from "@/entities/novel";
import { workKeys } from "@/entities/work";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

import { toNovelSourceRowAction } from "../model/novelSourceRow";

const PAGE_PATH = "/studio/new-novel";

/**
 * 스튜디오 "내 채팅으로 소설" — 소설로 엮을 내 대화를 고르는 화면. 방마다 막힌 이유 · 이미 만든 소설 열기 · 소설 만들기
 * 중 하나를 둔다. 소설 만들기는 빈 소설 하나를 만들 뿐이고(과금 없음) 화는 소설 화면에서 만든다.
 *
 * 폭은 대화방 목록(`/chats`)과 같은 글 컬럼 `max-w-2xl` 이다 — 행 끝의 버튼이 대화 이름 가까이 남아야 해서, 카드 목록처럼
 * 넓히지 않는다. 행 버튼은 모두 윤곽이다: 이 화면의 일은 여럿 중 하나를 고르는 것이라 솔리드 채움을 한 행에 몰지 않는다.
 */
export function StudioNewNovelPage() {
  const headingId = useId();

  return (
    <main aria-labelledby={headingId} className="mx-auto flex max-w-2xl flex-col gap-6 px-4 sm:px-6 py-10">
      <div className="flex flex-col gap-1">
        <Link
          to="/studio"
          className="-ml-1 mb-2 inline-flex w-fit items-center gap-0.5 rounded-md px-1 text-sm font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
        >
          <ChevronLeft aria-hidden className="size-4" />
          스튜디오 홈
        </Link>
        <h1 id={headingId} className="text-2xl font-bold tracking-tight text-foreground">
          내 채팅으로 소설
        </h1>
        <p className="text-sm break-keep text-muted-foreground">소설로 엮을 대화를 골라요. 화는 다음 화면에서 만들어요.</p>
      </div>
      <NovelSourceList />
    </main>
  );
}

/** 로딩 · 첫 페이지 실패 · 빈 목록 · 목록 넷. 다음 페이지 실패는 이미 받은 행을 지우지 않고 "더 보기" 가 남아 다시 누를 수
 * 있다(`ContentListLoadMore`). */
function NovelSourceList() {
  const query = useNovelSourcesQuery();
  const listRef = useRef<HTMLUListElement>(null);
  const createRoomNovel = useCreateRoomNovel(() => listRef.current?.focus());
  const blockedReason = toNovelizeForbiddenCopy(useCloverPricingQuery().data).room;

  if (query.isPending) return <NovelSourceListSkeleton />;

  if (query.isError && query.data === undefined) {
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3">
        <p className="text-sm break-keep text-destructive-text">대화 목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  const rooms = query.data.pages.flatMap((page) => page.items);

  if (rooms.length === 0) {
    return (
      <ContentListEmptyState
        title="아직 나눈 대화가 없어요"
        message="작품과 대화를 나누면 그 대화로 소설을 만들 수 있어요."
        action={
          <Button asChild variant="outline">
            <Link to="/">작품 둘러보기</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ul ref={listRef} tabIndex={-1} aria-label="내 대화" className="flex flex-col gap-2 outline-none">
        {rooms.map((room) => (
          <li key={room.id}>
            <NovelSourceRow
              room={room}
              blockedReason={blockedReason}
              isCreating={createRoomNovel.pendingRoomId === room.id}
              isAnyCreating={createRoomNovel.pendingRoomId !== undefined}
              onCreate={() => createRoomNovel.create(room.id)}
            />
          </li>
        ))}
      </ul>
      <ContentListLoadMore
        hasMore={query.hasNextPage}
        isLoading={query.isFetchingNextPage}
        onLoadMore={() => {
          if (!query.isFetchingNextPage) void query.fetchNextPage();
        }}
        onExhausted={() => listRef.current?.focus()}
      />
    </div>
  );
}

type NovelSourceRowProps = {
  room: NovelSourceRoom;
  blockedReason: string;
  isCreating: boolean;
  isAnyCreating: boolean;
  onCreate: () => void;
};

/** 행 자체는 누르는 곳이 아니다 — 방마다 하는 일이 달라 끝의 버튼(또는 막힌 이유)이 그 일을 말한다. 썸네일·작품명·방
 * 이름·마지막 메시지·시각은 내 채팅 목록 행과 같은 배치라 같은 방으로 알아본다. */
function NovelSourceRow({ room, blockedReason, isCreating, isAnyCreating, onCreate }: NovelSourceRowProps) {
  const action = toNovelSourceRowAction(room);
  const relativeTime = formatRelativeTime(room.lastMessageAt ?? room.createdAt, new Date());

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border p-3">
      {/* 썸네일 웰은 `bg-secondary` — 페이지 배경 위에서 보여야 한다(DESIGN.md Cards / Containers). */}
      <div className="size-10 shrink-0 overflow-hidden rounded-lg bg-secondary">
        {room.thumbnailUrl ? (
          <img src={room.thumbnailUrl} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden className="size-4" />
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 basis-40 flex-col gap-0.5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
            {room.contentName}
            <span className="text-xs font-medium text-muted-foreground"> · {room.name}</span>
          </p>
          <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">{relativeTime}</span>
        </div>
        {/* 메시지 0개인 방은 미리보기가 빈 문자열이라 공백으로 줄 높이를 지킨다(내 채팅 목록 행과 같은 이유). */}
        <p className="truncate text-xs text-muted-foreground">{stripChatNotation(room.lastMessagePreview) || " "}</p>
      </div>

      {action.kind === "blocked" && (
        <p className="w-full text-xs break-keep text-muted-foreground sm:w-auto sm:max-w-56 sm:text-right">
          {blockedReason}
        </p>
      )}
      {action.kind === "open" && (
        <Button asChild variant="outline" size="sm" className="shrink-0 pointer-coarse:h-10">
          <Link to="/novels/$novelId" params={{ novelId: action.novelId }}>
            소설 열기
          </Link>
        </Button>
      )}
      {action.kind === "create" && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          // 누른 뒤 응답까지 다른 행도 막는다 — 두 방의 소설을 연달아 만들면 마지막 응답의 소설로만 옮겨 가 앞의 것은 말없이
          // 만들어진다. `disabled` 가 아닌 이유는 실패해 돌아왔을 때 포커스가 이 버튼에 남아 있어야 해서다(그 사이 막혀 버튼이
          // 사라지는 실패는 목록으로 옮긴다).
          aria-disabled={isAnyCreating || undefined}
          aria-busy={isCreating || undefined}
          onClick={() => {
            if (!isAnyCreating) onCreate();
          }}
          className="shrink-0 aria-disabled:pointer-events-none aria-disabled:opacity-65 pointer-coarse:h-10"
        >
          {isCreating ? "만드는 중…" : "소설 만들기"}
        </Button>
      )}
    </div>
  );
}

/** 방의 소설을 만들고 그 소설 화면으로 옮긴다. 실패는 채팅 방 더보기의 「소설로 보기」와 같은 네 갈래로 알린다.
 * `onRowBlocked` 는 그 사이 막혀 누른 버튼이 이유 문장으로 바뀐 뒤 부른다 — 버튼과 함께 포커스가 사라지지 않게 목록으로
 * 옮기는 자리다. */
function useCreateRoomNovel(onRowBlocked: () => void) {
  const ensureRoomNovel = useEnsureRoomNovelMutation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const router = useRouter();
  const blockedReason = toNovelizeForbiddenCopy(useCloverPricingQuery().data).room;

  async function create(roomId: string) {
    try {
      const novel = await ensureRoomNovel.mutateAsync(roomId);
      // 이 쓰기가 낡게 만드는 캐시 — 이 목록(그 방이 "소설 열기"가 된다)과 스튜디오 작품 목록(소설 행이 는다). 두 쿼리는
      // 앱 기본 신선도라 다음에 화면을 열 때 어차피 다시 받지만, 신선도를 늘리는 쿼리가 생겨도 낡지 않게 여기서 표시해
      // 둔다. 소설 상세와 내 소설 목록은 뮤테이션 자신이 맡는다.
      void queryClient.invalidateQueries({ queryKey: novelKeys.sources() });
      void queryClient.invalidateQueries({ queryKey: workKeys.lists() });
      // 응답을 기다리는 사이 다른 화면으로 옮겼다면 소설 화면으로 끌고 가지 않는다(소설 상세는 이미 캐시에 있다).
      if (router.state.location.pathname !== PAGE_PATH) return;
      void navigate({ to: "/novels/$novelId", params: { novelId: novel.id } });
    } catch (error) {
      // 재동의가 필요하면 전역 처리가 재동의 모달을 띄운다 — 토스트를 겹치지 않는다.
      if (isLegalReconsentRequiredError(error)) return;
      // 목록을 받은 뒤 막힌 경우다(원작자가 허락을 거뒀다). 목록을 다시 받아 이 행도 막힌 이유를 보이게 한다.
      if (isContentNovelizeForbiddenError(error)) {
        toast.error(blockedReason);
        await queryClient.invalidateQueries({ queryKey: novelKeys.sources() });
        onRowBlocked();
        return;
      }
      // 허용을 회수한 직후라면 전역 처리가 세션을 다시 읽어 이 화면이 스튜디오로 돌아간다.
      toast.error(
        isNovelizeNotAllowedError(error)
          ? "아직 열리지 않은 기능이에요."
          : "소설을 만들지 못했어요. 잠시 후 다시 시도해주세요.",
      );
    }
  }

  return {
    create: (roomId: string) => void create(roomId),
    pendingRoomId: ensureRoomNovel.isPending ? ensureRoomNovel.variables : undefined,
  };
}

function NovelSourceListSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-2">
      {[0, 1, 2, 3].map((key) => (
        <div key={key} className="h-16 animate-pulse rounded-lg bg-muted" />
      ))}
    </div>
  );
}
