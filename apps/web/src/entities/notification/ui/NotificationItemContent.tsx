import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronRight } from "lucide-react";

import { assertNever } from "@/shared/lib/assertNever";

import type { NotificationResponse, ReportReasonCategory } from "../model/notification";
import { resolveNotificationDestination } from "../model/notificationDestination";

/** 알림의 사유는 서버가 작품·댓글 신고 사유 값을 그대로 복사해 둔 것이다(응답 스키마에서는 문자열). 생성된
 * 사유 타입을 키로 받는 `Record` 라 서버가 사유를 더하고 api-types 를 다시 만들면 라벨을 넣기 전까지 typecheck
 * 가 깨진다 — 문자열 키였을 때는 빠뜨려도 알림에 원문 값이 그대로 떴다. */
const REASON_CATEGORY_LABELS: Record<ReportReasonCategory, string> = {
  adult: "선정성",
  minor_safety: "아동·청소년 관련",
  copyright: "저작권 침해",
  hate: "혐오·차별",
  spam: "스팸",
  other: "기타",
};

function isReportReasonCategory(value: string): value is ReportReasonCategory {
  return value in REASON_CATEGORY_LABELS;
}

/** 댓글이 붙지 않은 알림의 type별 제목 — 이용제한/삭제 조치 통지(moderation-action), 계정 경고(user-warned),
 * 계정 정지(user-suspended), 공지(notice), 문의 답변(inquiry-reply). 댓글 알림(`comment-*`)은 아래
 * `notification.comment` 분기가 따로 제목을 만든다. type별로 제목 문구만 가르는 최소 구현이고, 모르는
 * type은 이용제한 문구로 폴백한다 — 여전히 범용 알림 프레임워크는 아니다. */
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
  const comment = notification.comment;
  if (comment) {
    let title: string;
    if (notification.type === "comment-moderated") title = "댓글 운영 안내";
    else if (comment.availability === "unavailable") title = "현재 확인할 수 없는 댓글 알림";
    else if (comment.isSpoiler) title = "스포일러가 포함된 댓글 알림";
    else {
      const author = comment.author?.nickname ?? "사용자";
      if (notification.type === "comment-reply") title = author + "님이 답글을 남겼어요.";
      else if (notification.type === "comment-mention") title = author + "님이 나를 멘션했어요.";
      else title = author + "님이 작품에 댓글을 남겼어요.";
    }
    const preview = comment.availability === "available" && !comment.isSpoiler
      ? (comment.bodyPreview || comment.stickerName) ?? undefined : undefined;
    return <span className="flex min-w-0 w-full items-center justify-between gap-2">
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className={cn("break-keep text-sm", !notification.read && "font-semibold text-foreground")}>{title}</span>
        {!!preview && <span className="line-clamp-2 text-xs text-muted-foreground wrap-anywhere">{preview}</span>}
        {notification.type === "comment-moderated" && <span className="line-clamp-2 text-xs text-muted-foreground">{notification.adminComment}</span>}
      </span><ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
    </span>;
  }

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
      case "comment":
        title = "댓글 알림";
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
          ` · ${isReportReasonCategory(notification.reasonCategory) ? REASON_CATEGORY_LABELS[notification.reasonCategory] : notification.reasonCategory}`}
      </span>
      <span className="line-clamp-2 text-xs text-muted-foreground">{notification.adminComment}</span>
    </>
  );
}
