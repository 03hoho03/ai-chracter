import { Button } from "@ai-character-chat/ui/components/button";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@ai-character-chat/ui/components/sheet";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate } from "@tanstack/react-router";
import { useAtomValue } from "jotai";
import { Bell, ChevronDown, LogIn, LogOut, Menu } from "lucide-react";
import { useEffect, useId, useRef, useState, type ComponentProps } from "react";
import { toast } from "sonner";

import { contentTypeToggleAtom } from "@/entities/content";
import {
  NotificationItemContent,
  resolveNotificationDestination,
  useMarkNotificationReadMutation,
  useNotificationListQuery,
  type NotificationResponse,
} from "@/entities/notification";
import { useSessionQuery } from "@/entities/session";
import { useLogoutMutation } from "@/features/logout";

import { ContentTypeToggle } from "./ContentTypeToggle";
import { PROFILE_DESTINATION_GROUPS, ProfileDestinationLink } from "./ProfileMenu";

const ROW_CLASS =
  "flex items-center gap-2.5 rounded-md px-2.5 py-2.5 text-left text-sm text-foreground motion-safe:transition-colors hover:bg-secondary/50 focus-visible:bg-secondary/50 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50 aria-disabled:opacity-65 [&_svg]:size-4 [&_svg]:shrink-0";

const DIVIDER_CLASS = "my-1 h-px shrink-0 border-0 bg-border";

// 목적지 없는 알림(조치 통지 3종)은 제목줄 + `adminComment` 2줄이라 다른 행과 달리 세로로 쌓는다.
const NOTIFICATION_ACTION_ROW_CLASS = cn(ROW_CLASS, "flex-col items-start gap-0.5");

/**
 * main-refact-goal-prompt.md MR-9~MR-11·MR-14, main-refact-progress.md S3b 착수 전 정정 —
 * `sm` 미만 헤더가 숨긴 텍스트 탭·이미지 생성·알림·프로필을 담는 좌측 시트. 이 저장소의 첫
 * `Sheet side="left"`다(기존 3곳은 전부 `side="bottom"`). **자기완결 위젯**(`apps/web/CLAUDE.md`
 * §레이아웃·이미지)이라 트리거(버거)와 열림 상태를 이 컴포넌트가 소유하고, `Header`는
 * `<MobileNavDrawer />` 하나만 배치한다.
 */
export function MobileNavDrawer({ className }: { className?: string }) {
  const { data: me } = useSessionQuery();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const logout = useLogoutMutation();

  // MR-14 — 드로어에서 유형을 바꾸면 `ContentTypeToggle`이 내부에서 재클릭 가드를 통과한 값을
  // atom에 쓰고 `navigate({ to: "/" })`를 부른다(로직은 그 컴포넌트 한 곳에만 둔다 — 여기서 다시
  // 구현하면 "17곳 중 2곳만 맞았다"류 복제 실패가 재현된다). 드로어가 열린 채 남으면 홈으로 이동한
  // 결과(그리드가 캐릭터/스토리로 바뀐 것)를 사용자가 볼 수 없으므로, 값이 바뀔 때 이 위젯이 직접
  // 닫는다. 마운트 시점의 초깃값과 동일한 첫 effect 실행에서 닫히면 안 되므로 첫 번째는 건너뛴다.
  const contentType = useAtomValue(contentTypeToggleAtom);
  const isFirstContentTypeChange = useRef(true);
  useEffect(() => {
    if (isFirstContentTypeChange.current) {
      isFirstContentTypeChange.current = false;
      return;
    }
    setOpen(false);
  }, [contentType]);

  function handleLogout() {
    if (logout.isPending) return;
    logout.mutate(undefined, {
      onSuccess: () => {
        toast.success("로그아웃되었어요.");
        setOpen(false);
        void navigate({ to: "/" });
      },
      onError: () => {
        toast.error("로그아웃에 실패했어요. 잠시 후 다시 시도해주세요.");
      },
    });
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        {me ? <BurgerButtonWithUnreadDot className={className} /> : <BurgerButton className={className} />}
      </SheetTrigger>
      <SheetContent side="left">
        <SheetHeader>
          <SheetTitle>메뉴</SheetTitle>
        </SheetHeader>

        <nav className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2 pb-3">
          <div className="px-0.5 py-1">
            {/* MR-14 — 가로 pill 쌍(`variant="outline"`). 헤더는 라벨만 있는 텍스트 탭(`"tab"`, 기본값),
                드로어는 버튼 크기 항목 둘이라 감사 테스트대로 기본 채움을 쓴다(`DESIGN.md` §Toggles). */}
            <ContentTypeToggle variant="outline" />
          </div>

          <hr className={DIVIDER_CLASS} />

          {/* 알림 섹션은 로그인 사용자 전용이다 — `useNotificationListQuery`는 앱 전체에서 로그인
              상태에서만 마운트되는 컴포넌트 안에서만 호출된다(그 훅 자신의 문서화). 비로그인에서는
              행과 구분선을 통째로 건너뛴다. */}
          {me && (
            <>
              <NotificationDisclosure />
              <hr className={DIVIDER_CLASS} />
            </>
          )}

          {me ? (
            <>
              {PROFILE_DESTINATION_GROUPS.flatMap((group) => group.keys).map((key) => (
                <SheetClose asChild key={key}>
                  <ProfileDestinationLink destinationKey={key} me={me} className={ROW_CLASS} />
                </SheetClose>
              ))}
              {/* 로그아웃은 `destructive`가 아니다 — `ProfileMenu`가 3단 근거(지우는 게 없고 다시 로그인하면
                  되돌아온다 / 앱의 다른 destructive 4항목은 전부 데이터를 지운다 / `MyPagePage`의 로그아웃이
                  이미 `outline`)로 중립으로 정한 결정을 그대로 따른다. 비동기 액션이라 `aria-disabled` +
                  핸들러 첫 줄 early return을 쓴다(`disabled`는 클릭마다 blur를 일으켜 포커스가 사라진다 —
                  `apps/web/CLAUDE.md` §포커스). */}
              <button type="button" aria-disabled={logout.isPending} onClick={handleLogout} className={ROW_CLASS}>
                <LogOut aria-hidden />
                로그아웃
              </button>
            </>
          ) : (
            <SheetClose asChild>
              <Link to="/login" className={ROW_CLASS}>
                <LogIn aria-hidden />
                로그인
              </Link>
            </SheetClose>
          )}
        </nav>
      </SheetContent>
    </Sheet>
  );
}

// `SheetTrigger asChild`는 Radix가 만든 props(무엇보다 열기 `onClick`·`ref`·`data-state`)를 바로 아래
// 자식 엘리먼트에 병합해 얹는다 — 그 자식이 이 함수 컴포넌트이므로, `...props`를 실제 `<Button>`까지
// 그대로 흘려보내지 않으면 병합된 `onClick`이 여기서 조용히 버려져 버거를 눌러도 시트가 안 열린다.
function BurgerButton({ className, ...props }: ComponentProps<typeof Button>) {
  return (
    <Button type="button" variant="ghost" size="icon" aria-label="메뉴 열기" className={className} {...props}>
      <Menu aria-hidden />
    </Button>
  );
}

/** MR-11(정정) — 개수가 아니라 점 하나, 색은 `bg-foreground`다. `bg-accent`(0.260)는 헤더 배경(0.160)
 * 대비 약 1.25:1로 베어 점으로 쓰면 안 보이고, `primary`는 무채색으로 충분한 신호에 이 시스템의 유일한
 * 유채색 예산을 쓰는 셈이라(One-Accent Rule) 기각했다 — `DESIGN.md` §Status badges의 "사용자가 읽을 게
 * 생긴 상태만 밝기 천장 `text-foreground`로 올린다"(문의 `답변완료` 선례)와 같은 규범이다. 개수는 노출하지
 * 않는다(버거는 여러 항목의 수납구라 숫자를 달면 무엇의 개수인지 모호해진다) — 개수는 드로어 안
 * `NotificationDisclosure`가 진다. */
function BurgerButtonWithUnreadDot({ className, ...props }: ComponentProps<typeof Button>) {
  const { data: notifications = [] } = useNotificationListQuery();
  const hasUnread = notifications.some((notification) => !notification.read);

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={hasUnread ? "메뉴 열기, 읽지 않은 알림 있음" : "메뉴 열기"}
      className={cn("relative", className)}
      {...props}
    >
      <Menu aria-hidden />
      {hasUnread && <span aria-hidden className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-foreground" />}
    </Button>
  );
}

/** MR-10a — 알림 벨이 `sm` 미만에서 숨어 알림을 열어볼 방법이 없던 퇴행을 고친다. 시트 안에서 Radix
 * 드롭다운을 다시 열면 안 되므로(`apps/web/CLAUDE.md` §메뉴·모달) 인라인 disclosure로 편다. */
function NotificationDisclosure() {
  const listId = useId();
  const [isExpanded, setIsExpanded] = useState(false);
  const { data: notifications = [] } = useNotificationListQuery();
  const markAsRead = useMarkNotificationReadMutation();
  const unreadCount = notifications.filter((notification) => !notification.read).length;

  return (
    <>
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={listId}
        onClick={() => setIsExpanded((prev) => !prev)}
        className={ROW_CLASS}
      >
        <Bell aria-hidden />
        <span className="flex-1">알림</span>
        {unreadCount > 0 && (
          <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-badge leading-none font-semibold text-accent-foreground">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
        <ChevronDown aria-hidden className={cn("motion-safe:transition-transform", isExpanded && "rotate-180")} />
      </button>
      {isExpanded && (
        // 별도 `max-h`로 가두지 않는다 — 부모 `<nav>`가 이미 `min-h-0 flex-1 overflow-y-auto`라 시트 안
        // 모든 행(콘텐츠 유형 토글~로그아웃)을 아우르는 스크롤 컨테이너를 갖고 있다. 알림이 많아 이
        // 목록이 시트 높이를 넘기면 nav 전체가 스크롤되어 위아래 다른 행도 계속 스크롤로 닿는다.
        <div id={listId} className="flex flex-col gap-0.5">
          {notifications.length === 0 ? (
            <p className="px-2.5 py-4 text-center text-sm text-muted-foreground">아직 알림이 없어요.</p>
          ) : (
            notifications.map((notification) => (
              <NotificationDrawerItem
                key={notification.id}
                notification={notification}
                onRead={(id) => markAsRead.mutate(id)}
              />
            ))
          )}
        </div>
      )}
    </>
  );
}

// 드롭다운(`NotificationBell`)과 같은 의미(D-17): 목적지가 있는 공지·문의 답변은 이동 링크,
// 조치 통지 3종은 갈 곳이 없어 읽음 처리만 한다. `SheetClose asChild`의 자식은 반드시 `Link` 자신이어야
// 한다 — 커스텀 컴포넌트를 끼우면 Radix Slot이 얹는 onClick/ref가 전달되지 않아 조용히 안 닫힌다.
function NotificationDrawerItem({
  notification,
  onRead,
}: {
  notification: NotificationResponse;
  onRead: (id: string) => void;
}) {
  const destination = resolveNotificationDestination(notification);

  if (destination.kind === "notice") {
    return (
      <SheetClose asChild>
        <Link
          to="/notices/$noticeId"
          params={{ noticeId: destination.noticeId }}
          onClick={() => {
            if (!notification.read) onRead(notification.id);
          }}
          className={ROW_CLASS}
        >
          <NotificationItemContent notification={notification} />
        </Link>
      </SheetClose>
    );
  }

  if (destination.kind === "inquiry") {
    return (
      <SheetClose asChild>
        <Link
          to="/inquiries/$inquiryId"
          params={{ inquiryId: destination.inquiryId }}
          onClick={() => {
            if (!notification.read) onRead(notification.id);
          }}
          className={ROW_CLASS}
        >
          <NotificationItemContent notification={notification} />
        </Link>
      </SheetClose>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        if (!notification.read) onRead(notification.id);
      }}
      className={NOTIFICATION_ACTION_ROW_CLASS}
    >
      <NotificationItemContent notification={notification} />
    </button>
  );
}
