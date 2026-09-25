import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronRight } from "lucide-react";

import { assertNever } from "@/shared/lib/assertNever";

import type { NotificationResponse } from "../api/useNotificationListQuery";
import { resolveNotificationDestination } from "../model/notificationDestination";

const REASON_CATEGORY_LABELS: Record<string, string> = {
  adult: "선정성",
  copyright: "저작권 침해",
  hate: "혐오·차별",
  spam: "스팸",
  other: "기타",
};

/** 이용제한/삭제 조치 통지(moderation-action)에 계정 경고(user-warned)·
 * 계정 정지(user-suspended)·공지(notice)·문의 답변(inquiry-reply)이 더해져 `type`이
 * 다섯이 됐다. type별로 제목 문구만 가르는 최소 구현이고, 모르는 type은 이용제한 문구로
 * 폴백한다 — 여전히 범용 알림 프레임워크는 아니다. */
const NOTIFICATION_TITLE_BY_TYPE: Record<string, string> = {
  "moderation-action": "콘텐츠 이용제한 안내",
  "user-warned": "계정 경고 안내",
  "user-suspended": "계정 이용정지 안내",
  notice: "공지사항",
  "inquiry-reply": "문의 답변",
};

/** 알림 항목의 안쪽 내용만 그린다(래퍼 없음) — 목적지가 있으면 제목줄 + 화살표, 없으면 제목줄 +
 * 관리자 코멘트 2줄 클램프. 호스트(드롭다운/드로어)가 각자의 래퍼(`DropdownMenuItem`/`Link` 등)를 씌운다. */
export function NotificationItemContent({ notification }: { notification: NotificationResponse }) {
  const destination = resolveNotificationDestination(notification);

  if (destination.kind !== "none") {
    // 삼항이면 새 kind가 추가돼도 `!== "none"`을 그대로 통과해 무조건 "문의 답변" 제목을 달고 나간다 —
    // switch + default: assertNever로 kind마다 명시적으로 갈라, 새 멤버가 생기면 타입에러로 막는다.
    let title: string | undefined;
    switch (destination.kind) {
      case "notice":
        title = NOTIFICATION_TITLE_BY_TYPE.notice;
        break;
      case "inquiry":
        title = NOTIFICATION_TITLE_BY_TYPE["inquiry-reply"];
        break;
      default:
        return assertNever(destination);
    }

    return (
      <span className="flex w-full items-center justify-between gap-2">
        <span className={cn("text-sm", !notification.read && "font-semibold text-foreground")}>
          {title} · {notification.title}
        </span>
        <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      </span>
    );
  }

  return (
    <>
      <span className={cn("text-sm", !notification.read && "font-semibold text-foreground")}>
        {NOTIFICATION_TITLE_BY_TYPE[notification.type] ?? NOTIFICATION_TITLE_BY_TYPE["moderation-action"]}
        {notification.reasonCategory != null &&
          ` · ${REASON_CATEGORY_LABELS[notification.reasonCategory] ?? notification.reasonCategory}`}
      </span>
      <span className="line-clamp-2 text-xs text-muted-foreground">{notification.adminComment}</span>
    </>
  );
}
