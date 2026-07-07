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
import { Bell } from "lucide-react";

import { useMarkNotificationReadMutation, useNotificationListQuery } from "../../../entities/notification";

const REASON_CATEGORY_LABELS: Record<string, string> = {
  adult: "선정성",
  copyright: "저작권 침해",
  hate: "혐오·차별",
  spam: "스팸",
  other: "기타",
};

/** techspec-global-nav-profile.md §1.3, techspec-builder-common.md §5.2 — 알림 종류는 현재 이용제한/삭제
 * 조치 통지(US-055) 하나뿐이라 범용 알림 프레임워크로 만들지 않는다. */
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
            <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] leading-none font-semibold text-accent-foreground">
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
          notifications.map((notification) => (
            <DropdownMenuItem
              key={notification.id}
              className="flex flex-col items-start gap-0.5 py-2 whitespace-normal"
              onSelect={(event) => {
                // 여러 알림을 이어서 확인할 수 있도록 클릭 후에도 드롭다운을 열어둔다.
                event.preventDefault();
                if (!notification.read) markAsRead.mutate(notification.id);
              }}
            >
              <span className={cn("text-sm", !notification.read && "font-semibold text-foreground")}>
                콘텐츠 이용제한 안내 ·{" "}
                {REASON_CATEGORY_LABELS[notification.reasonCategory] ?? notification.reasonCategory}
              </span>
              <span className="line-clamp-2 text-xs text-muted-foreground">{notification.adminComment}</span>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
