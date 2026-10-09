import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { useAtom } from "jotai";

import { contentDetailModalAtom } from "@/entities/content";
import {
  NotificationItemContent,
  resolveNotificationDestination,
  useMarkNotificationReadMutation,
  useNotificationListQuery,
  useNotificationUnreadCountQuery,
  type NotificationResponse,
} from "@/entities/notification";
import { assertNever } from "@/shared/lib/assertNever";

import { NotificationFeedStatus } from "./NotificationFeedStatus";

export function NotificationBell({ viewerId }: { viewerId: string }) {
  const query = useNotificationListQuery(viewerId);
  const notifications = [...new Map((query.data?.pages.flatMap((page) => page.items) ?? []).map((item) => [item.id, item])).values()];
  const markAsRead = useMarkNotificationReadMutation(viewerId);
  const unreadCount = useNotificationUnreadCountQuery(viewerId).data?.unreadCount ?? 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={unreadCount > 0 ? `알림, 읽지 않은 알림 ${unreadCount}개` : "알림"}
        >
          <Bell aria-hidden />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-badge leading-none font-semibold text-accent-foreground">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72 max-h-[min(70dvh,var(--radix-dropdown-menu-content-available-height))] overflow-y-auto">
        <DropdownMenuLabel>알림</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {notifications.length === 0 && !query.isPending && !query.isError ? (
          <p className="px-1.5 py-4 text-center text-sm text-muted-foreground">아직 알림이 없어요.</p>
        ) : (
          // 이 목록은 항목마다 동작이 갈린다: 공지·문의 답변은 목적지(`/notices/$noticeId`·
          // `/inquiries/$inquiryId`)가 있어 링크지만, 조치 통지 3종은 경고·정지가 content_id 없이
          // 갈 곳이 없고 이용제한 콘텐츠로 보내면 오류 화면이라 갈 곳이 없다 — 읽음 처리만 하고
          // 드롭다운을 열어둔다.
          notifications.map((notification) => (
            <NotificationListItem
              key={notification.id}
              notification={notification}
              onRead={(id) => markAsRead.mutate(id)}
            />
          ))
        )}
        <NotificationFeedStatus isPending={query.isPending} hasError={query.isError} hasNext={!!query.hasNextPage} isFetchingNext={query.isFetchingNextPage}
          onRetry={() => { if (query.isFetchNextPageError) void query.fetchNextPage(); else void query.refetch(); }}
          onMore={() => void query.fetchNextPage()} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function NotificationListItem({
  notification,
  onRead,
}: {
  notification: NotificationResponse;
  onRead: (id: string) => void;
}) {
  const destination = resolveNotificationDestination(notification);
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);

  if (destination.kind === "comment") {
    return <DropdownMenuItem asChild className="py-2" onSelect={() => {
      if (!notification.read) onRead(notification.id);
      setModalState(undefined);
    }}><Link to="/content/$type/$id" params={{ type: destination.contentType, id: destination.contentId }}
      search={{ comment: destination.commentId }} replace={modalState !== undefined}>
      <NotificationItemContent notification={notification} />
    </Link></DropdownMenuItem>;
  }

  if (destination.kind === "notice") {
    return (
      <DropdownMenuItem
        asChild
        className="py-2"
        onSelect={() => {
          if (!notification.read) onRead(notification.id);
        }}
      >
        <Link to="/notices/$noticeId" params={{ noticeId: destination.noticeId }}>
          <NotificationItemContent notification={notification} />
        </Link>
      </DropdownMenuItem>
    );
  }

  if (destination.kind === "inquiry") {
    return (
      <DropdownMenuItem
        asChild
        className="py-2"
        onSelect={() => {
          if (!notification.read) onRead(notification.id);
        }}
      >
        <Link to="/inquiries/$inquiryId" params={{ inquiryId: destination.inquiryId }}>
          <NotificationItemContent notification={notification} />
        </Link>
      </DropdownMenuItem>
    );
  }

  if (destination.kind === "cloverHistory") {
    return (
      <DropdownMenuItem
        asChild
        className="py-2"
        onSelect={() => {
          if (!notification.read) onRead(notification.id);
        }}
      >
        <Link to="/clover/history" search={{ tab: "earn" }}>
          <NotificationItemContent notification={notification} />
        </Link>
      </DropdownMenuItem>
    );
  }

  if (destination.kind === "none") {
    return (
      <DropdownMenuItem
        className="flex flex-col items-start gap-0.5 py-2 whitespace-normal"
        onSelect={(event) => {
          // 여러 알림을 이어서 확인할 수 있도록 클릭 후에도 드롭다운을 열어둔다.
          event.preventDefault();
          if (!notification.read) onRead(notification.id);
        }}
      >
        <NotificationItemContent notification={notification} />
      </DropdownMenuItem>
    );
  }

  return assertNever(destination);
}
