import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { Bell, ChevronRight } from "lucide-react";

import {
  useMarkNotificationReadMutation,
  useNotificationListQuery,
  type NotificationResponse,
} from "@/entities/notification";

const REASON_CATEGORY_LABELS: Record<string, string> = {
  adult: "선정성",
  copyright: "저작권 침해",
  hate: "혐오·차별",
  spam: "스팸",
  other: "기타",
};

/** techspec.md §1-2 — 이용제한/삭제 조치 통지(moderation-action, US-055)에 계정 경고(user-warned)·
 * 계정 정지(user-suspended)·공지(notice, T-11b)·문의 답변(inquiry-reply, T-17)이 더해져 `type`이
 * 다섯이 됐다. type별로 제목 문구만 가르는 최소 구현이고, 모르는 type은 이용제한 문구로
 * 폴백한다 — 여전히 범용 알림 프레임워크는 아니다. */
const NOTIFICATION_TITLE_BY_TYPE: Record<string, string> = {
  "moderation-action": "콘텐츠 이용제한 안내",
  "user-warned": "계정 경고 안내",
  "user-suspended": "계정 이용정지 안내",
  notice: "공지사항",
  "inquiry-reply": "문의 답변",
};

export function NotificationBell() {
  const { data: notifications = [] } = useNotificationListQuery();
  const markAsRead = useMarkNotificationReadMutation();
  const unreadCount = notifications.filter((notification) => !notification.read).length;

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
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>알림</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {notifications.length === 0 ? (
          <p className="px-1.5 py-4 text-center text-sm text-muted-foreground">아직 알림이 없어요.</p>
        ) : (
          // 이 목록은 항목마다 동작이 갈린다(D-17): 공지·문의 답변은 목적지(`/notices/$noticeId`·
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
  if (notification.type === "notice" && notification.noticeId) {
    return (
      <DropdownMenuItem
        asChild
        className="py-2"
        onSelect={() => {
          if (!notification.read) onRead(notification.id);
        }}
      >
        <Link to="/notices/$noticeId" params={{ noticeId: notification.noticeId }}>
          <span className="flex w-full items-center justify-between gap-2">
            <span className={cn("text-sm", !notification.read && "font-semibold text-foreground")}>
              {NOTIFICATION_TITLE_BY_TYPE.notice} · {notification.title}
            </span>
            <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          </span>
        </Link>
      </DropdownMenuItem>
    );
  }

  if (notification.type === "inquiry-reply" && notification.inquiryId) {
    return (
      <DropdownMenuItem
        asChild
        className="py-2"
        onSelect={() => {
          if (!notification.read) onRead(notification.id);
        }}
      >
        <Link to="/inquiries/$inquiryId" params={{ inquiryId: notification.inquiryId }}>
          <span className="flex w-full items-center justify-between gap-2">
            <span className={cn("text-sm", !notification.read && "font-semibold text-foreground")}>
              {NOTIFICATION_TITLE_BY_TYPE["inquiry-reply"]} · {notification.title}
            </span>
            <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          </span>
        </Link>
      </DropdownMenuItem>
    );
  }

  return (
    <DropdownMenuItem
      className="flex flex-col items-start gap-0.5 py-2 whitespace-normal"
      onSelect={(event) => {
        // 여러 알림을 이어서 확인할 수 있도록 클릭 후에도 드롭다운을 열어둔다.
        event.preventDefault();
        if (!notification.read) onRead(notification.id);
      }}
    >
      <span className={cn("text-sm", !notification.read && "font-semibold text-foreground")}>
        {NOTIFICATION_TITLE_BY_TYPE[notification.type] ?? NOTIFICATION_TITLE_BY_TYPE["moderation-action"]}
        {notification.reasonCategory != null &&
          ` · ${REASON_CATEGORY_LABELS[notification.reasonCategory] ?? notification.reasonCategory}`}
      </span>
      <span className="line-clamp-2 text-xs text-muted-foreground">{notification.adminComment}</span>
    </DropdownMenuItem>
  );
}
