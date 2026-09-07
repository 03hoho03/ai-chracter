import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ImageOff } from "lucide-react";

import { useMyChatRoomListQuery, type MyChatRoomListItem } from "@/entities/chat-room";
import { ContentListEmptyState } from "@/entities/content";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

/** 헤더 "내 채팅목록"(파라미터 없이 진입)에서 보이는 전체 대화방 목록 — 콘텐츠 스코프 없이 한 번에
 * 받는다(`GET /me/chat-rooms`). 이름변경·초기화·삭제는 다루지 않는다(읽기+열기만) — 그 조작은
 * 콘텐츠 스코프 목록(`ChatRoomListView`, `/chats?contentId=`)의 몫으로 남는다. */
export function MyChatRoomListView() {
  const listQuery = useMyChatRoomListQuery();

  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-4 px-4 sm:px-6 py-10">
      <h1 className="text-xl font-bold tracking-tight text-foreground">내 채팅목록</h1>

      {listQuery.isPending && <MyChatRoomListSkeleton />}

      {listQuery.isError && (
        <p className="text-sm text-destructive-text">목록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
      )}

      {listQuery.data && listQuery.data.length === 0 && (
        <ContentListEmptyState
          message="아직 시작한 대화가 없어요."
          action={
            <Button asChild>
              <Link to="/">홈으로 가기</Link>
            </Button>
          }
        />
      )}

      {listQuery.data && listQuery.data.length > 0 && (
        <div className="flex flex-col gap-2">
          {listQuery.data.map((item) => (
            <MyChatRoomListItemRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </main>
  );
}

function MyChatRoomListSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {[0, 1, 2, 3].map((key) => (
        <div key={key} className="h-16 animate-pulse rounded-lg bg-muted" />
      ))}
    </div>
  );
}

/** 전체 목록에서는 같은 콘텐츠에 방이 여러 개일 수 있고 이름 없는 방은 전부 `대화 N`이라, 작품명 없이는
 * 구분이 안 된다(실제 dev 데이터에 서로 다른 두 작품의 `대화 1`이 동시에 존재). 그래서 작품명을 1차
 * 식별자로 크게(`text-sm font-semibold`, `ContentCard` 제목과 같은 레시피), 방 이름은 시각과 함께
 * 메타(`text-xs text-muted-foreground`)로 묶어 한 줄에 둔다. 행 높이(66px)는 텍스트 줄 수가 아니라
 * 썸네일 40px + `p-3` + 보더가 정한다 — 텍스트 열은 38px로 그 아래에 들어가고, 그래서 스켈레톤 `h-16`
 * (64px)과 2px 차이로 맞는다. */
function MyChatRoomListItemRow({ item }: { item: MyChatRoomListItem }) {
  const relativeTime = formatRelativeTime(item.lastMessageAt ?? item.createdAt, new Date());

  return (
    <Link
      to="/chat/$roomId"
      params={{ roomId: item.id }}
      className="flex items-center gap-3 rounded-lg border border-border bg-background p-3 outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px motion-safe:transition-colors"
    >
      {/* DESIGN.md §5 Cards — 썸네일 웰은 `bg-secondary`(`bg-muted`는 이 행의 `hover:bg-muted`와
          같은 값이 되어 hover 중 사라진다). */}
      <div className="size-10 shrink-0 overflow-hidden rounded-lg bg-secondary">
        {item.thumbnailUrl ? (
          <img
            src={item.thumbnailUrl}
            alt=""
            loading="lazy"
            decoding="async"
            className="size-full object-cover"
          />
        ) : (
          <div className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff aria-hidden className="size-4" />
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-baseline justify-between gap-2">
          <p className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
            {item.contentName}
            <span className="text-xs font-normal text-muted-foreground"> · {item.name}</span>
          </p>
          <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">{relativeTime}</span>
        </div>
        {/* 메시지 0개인 방은 lastMessagePreview가 빈 문자열이다. 리터럴 공백으로 이 줄의 라인박스를
            살려 둔다 — 행 높이가 달라지기 때문이 아니다(썸네일 40px + `p-3`가 지배해 양쪽 다 66px
            실측). 빈 문자열이면 텍스트 열이 38→22px로 줄고 `items-center` 정렬이 제목 줄을 14→22px로
            밀어 다른 행들과 8px 어긋난다(실측 A/B). `truncate`의 `white-space: nowrap`에서는 홀로
            남은 공백이 축약되지 않아 16px 라인박스가 유지된다. */}
        <p className="truncate text-xs break-keep text-muted-foreground">
          {item.lastMessagePreview || " "}
        </p>
      </div>
    </Link>
  );
}
