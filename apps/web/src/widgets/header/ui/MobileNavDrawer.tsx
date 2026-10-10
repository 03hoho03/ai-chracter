import { Button } from "@ai-character-chat/ui/components/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@ai-character-chat/ui/components/sheet";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { Bell, ChevronDown, LogIn, LogOut, Menu } from "lucide-react";
import { Fragment, useId, useRef, useState, type ComponentProps } from "react";
import { toast } from "sonner";
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
import { loginRedirectTarget, useSessionQuery } from "@/entities/session";
import { useLogoutMutation } from "@/features/logout";
import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";
import { isPublicSupportDestinationKey } from "@/shared/config/supportDestinations";
import { assertNever } from "@/shared/lib/assertNever";

import { NotificationFeedStatus } from "./NotificationFeedStatus";
import { ContentTypeToggle } from "./ContentTypeToggle";
import { ProfileDestinationLink } from "./ProfileDestinationLink";
import { RECENT_CHATS_HEAD_ATTR, RecentChatsSection } from "./RecentChatsSection";
import { SIDE_PANEL_ID } from "./SidePanel";
import { SIDE_PANEL_NAV_ROW_CLASS } from "./sidePanelRowClass";
import { useIsSidePanelLayout } from "../lib/useIsSidePanelLayout";
import { PROFILE_MENU_DESTINATION_GROUPS, SIDE_PANEL_DESTINATION_KEYS } from "../model/profileDestinations";
import { getSidePanelScreen } from "../model/sidePanelCollapse";
import { isProfileDestinationVisible } from "../model/profileDestinationVisibility";

const DIVIDER_CLASS = "my-1 h-px shrink-0 border-0 bg-border";

// 비로그인에게도 열리는 목적지(서비스 소개·공지사항·약관·처리방침)는 로그인 사용자의 메뉴 목록에서 공개 키만
// 고른다 — 순서도 그 목록을 따른다.
const PUBLIC_MENU_DESTINATION_KEYS = PROFILE_MENU_DESTINATION_GROUPS.flatMap((group) => group.keys).filter(
  isPublicSupportDestinationKey,
);

// 알림 항목은 제목·미리보기가 여러 줄이라 높이와 줄바꿈을 내용에 맡긴다 — 패널 행 레시피의 고정 높이·한 줄을 쓰지 않고
// hover·포커스만 같은 값으로 맞춘다. 글자색은 읽음 여부에 따라 내용(`NotificationItemContent`)이 정하므로 기본을 밝기
// 천장으로 둔다.
const NOTIFICATION_ROW_CLASS = cn(
  "flex items-center gap-2.5 rounded-lg px-4 py-2.5 text-left text-sm text-foreground",
  "motion-safe:transition-colors hover:bg-secondary",
  "focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring",
  "pointer-coarse:min-h-10 [&_svg]:size-4 [&_svg]:shrink-0",
);

// 목적지 없는 알림(조치 통지 3종)은 제목줄 + `adminComment` 2줄이라 다른 행과 달리 세로로 쌓는다.
const NOTIFICATION_ACTION_ROW_CLASS = cn(NOTIFICATION_ROW_CLASS, "flex-col items-start gap-0.5");

/**
 * `lg`(1024px) 미만의 좌측 시트. 그 폭에는 좌측 패널이 없고 헤더가 [버거 · 로고 · 검색] 셋뿐이라, 패널의 내용(내비 ·
 * 최근 대화)과 헤더에서 빠진 것(유형 전환 · 알림 · 프로필 메뉴의 목적지 · 로그아웃)을 모두 여기 담는다. 순서는 유형 전환 →
 * 알림 → 패널 내비 → 최근 대화 → 계정 → 고객센터 → 로그아웃이다 — 알림을 위에 두는 이유는 버거의 점(미확인 알림)이
 * 가리키는 대상이 스크롤 없이 보여야 해서다. 비로그인은 맨 위 로그인 행 → 유형 전환 → 패널 내비 → 최근 대화 자리의
 * 로그인 안내 → 로그인 없이 열리는 목적지다.
 *
 * 행은 패널과 같은 레시피(`SIDE_PANEL_NAV_ROW_CLASS`)다 — 같은 목적지가 패널과 드로어에서 다른 hover·현재 표시를 갖지
 * 않게. 이 시트는 `popover` 위라 최근 대화는 그 표면용 채움(`surface="popover"`)으로 그린다.
 *
 * **자기완결 위젯**(`apps/web/CLAUDE.md` 레이아웃·이미지 절)이라 트리거(버거)와 열림 상태를 이 컴포넌트가 소유하고,
 * `Header`는 `<MobileNavDrawer />` 하나만 배치한다.
 */
export function MobileNavDrawer({ className }: { className?: string }) {
  const { data: me, isPending: isSessionPending } = useSessionQuery();
  // 헤더의 "로그인"과 같은 규칙으로 로그인 뒤 돌아올 곳을 싣는다.
  const loginRedirect = useRouterState({ select: (state) => loginRedirectTarget(state.location) });
  const isChatRoom = useRouterState({ select: (state) => getSidePanelScreen(state.location.pathname) === "chat" });
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();
  const logout = useLogoutMutation();
  const isSidePanelLayout = useIsSidePanelLayout();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const isClosingForNavigationRef = useRef(false);
  const panelKeys = SIDE_PANEL_DESTINATION_KEYS.filter((key) => isProfileDestinationVisible(key, me?.enabledFeatures));

  // 드로어를 연 채 창을 `lg` 이상으로 넓히면 버거가 숨어 닫을 길이 스크림뿐이고, 그 폭에는 같은 내용의 패널이 생긴다 —
  // 넓어지는 순간 닫는다. 렌더 중 자기 상태를 고치는 것이라 효과 없이 한 번 더 렌더될 뿐이다.
  if (isSidePanelLayout && isOpen) setIsOpen(false);

  // 항목을 눌러 닫을 때. 닫힌 뒤 포커스를 버거가 아니라 새 화면 본문으로 보내려고 표시해 둔다(아래 `onCloseAutoFocus`).
  function handleNavigate() {
    isClosingForNavigationRef.current = true;
    setIsOpen(false);
  }

  function handleLogout() {
    if (logout.isPending) return;
    logout.mutate(undefined, {
      onSuccess: () => {
        toast.success("로그아웃되었어요.");
        setIsOpen(false);
        void navigate({ to: "/" });
      },
      onError: () => {
        toast.error("로그아웃에 실패했어요. 잠시 후 다시 시도해주세요.");
      },
    });
  }

  return (
    <Sheet open={isOpen} onOpenChange={setIsOpen}>
      <SheetTrigger asChild ref={triggerRef}>
        {me ? <BurgerButtonWithUnreadDot viewerId={me.id} className={className} /> : <BurgerButton className={className} />}
      </SheetTrigger>
      <SheetContent
        ref={contentRef}
        side="left"
        onOpenAutoFocus={(event) => {
          // 시트 안에서 DOM 순서상 첫 현재 화면 링크(`aria-current="page"` — 노벨 pill·패널 내비·현재 방·계정·고객센터
          // 목적지 어느 것이든)에서 시작한다. 채팅방인데 현재 방 행이 없으면(처음 열 때는 최근 대화가 아직 로딩 중이고,
          // 현재 방이 최근 10개 밖일 수도 있다) 현재 방이 놓일 최근 대화 섹션 이름에서 시작한다 — 첫 버튼(유형 전환)에서
          // 시작하면 지금 있는 곳과 무관한 자리에서 읽기가 시작된다. 목록이 도착한 뒤 포커스를 옮기지는 않는다(그새
          // 사용자가 움직였을 수 있다). 그 밖의 화면에서 현재 링크가 없으면 Radix 기본(첫 버튼)에 맡긴다.
          const content = contentRef.current;
          const current = content?.querySelector<HTMLElement>('a[aria-current="page"]');
          const target = current ?? (isChatRoom ? content?.querySelector<HTMLElement>(`[${RECENT_CHATS_HEAD_ATTR}]`) : null);
          if (!target) return;
          event.preventDefault();
          target.focus();
        }}
        onCloseAutoFocus={(event) => {
          const isNavigation = isClosingForNavigationRef.current;
          isClosingForNavigationRef.current = false;
          // 버거가 보이지 않으면(`lg` 이상으로 넓혀 강제로 닫힌 경우) Radix 기본 복귀 대상이 없어 포커스가 `<body>` 로 떨어진다.
          const isTriggerHidden = (triggerRef.current?.getClientRects().length ?? 0) === 0;
          // Esc·스크림·닫기 X 는 Radix 기본대로 버거로 돌아간다.
          if (!isNavigation && !isTriggerHidden) return;
          event.preventDefault();
          // 이동이 편집 화면의 이탈 확인으로 막혔으면 그 확인 창이 먼저 포커스를 가져갔다 — 빼앗지 않는다.
          const active = document.activeElement;
          const isHeldElsewhere =
            active !== null && active !== document.body && active.isConnected && !contentRef.current?.contains(active);
          if (isHeldElsewhere) return;
          // 항목을 눌러 닫혔으면 새 화면 본문에서 읽기가 시작되게 본문으로 보낸다. 강제로 닫혔으면 그 순간 생긴 패널의 현재
          // 항목(내비 행·현재 방 행 — 로고는 목록 밖이라 고르지 않는다)으로, 없으면 본문으로 보낸다. 이 콜백은 시트가 다
          // 닫힌 뒤에 불려 그때는 패널이 이미 마운트돼 있다.
          const panelCurrent = isNavigation
            ? null
            : document.querySelector<HTMLElement>(`#${SIDE_PANEL_ID} li a[aria-current="page"]`);
          (panelCurrent ?? document.getElementById(MAIN_CONTENT_ID))?.focus();
        }}
      >
        <SheetHeader className="px-6">
          <SheetTitle>메뉴</SheetTitle>
        </SheetHeader>

        <nav className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-3">
          {!me && (
            <Link to="/login" search={{ redirect: loginRedirect }} onClick={handleNavigate} className={SIDE_PANEL_NAV_ROW_CLASS}>
              <LogIn aria-hidden />
              로그인
            </Link>
          )}

          <div className="px-4 pt-1 pb-2">
            {/* 가로 pill 줄(`variant="outline"`) — 캐릭터·스토리 토글 쌍과 그 옆 "노벨" 링크. 헤더는 라벨만
                있는 텍스트 탭(`"tab"`, 기본값), 드로어는 버튼 크기 항목이라 감사 테스트대로 기본 채움을 쓴다
                (`DESIGN.md` Toggles 절). 이 줄은 로그인과 무관하게 나오므로 비로그인도 여기서 노벨로 갈 수 있다(라우트의
                `requireSession`이 로그인으로 보낸다). 링크를 누르면 `onSelected`로 닫힌다.

                드로어가 열린 채 남으면 홈으로 이동한 결과(그리드가 캐릭터/스토리로
                바뀐 것)를 사용자가 볼 수 없으므로 닫아야 한다. 이전엔 atom을 `useAtomValue`로 관찰하고
                `useEffect`+`useRef` 첫-실행 가드로 닫았는데, `ContentTypeToggle`이 재클릭 가드를 통과한
                뒤에만 부르는 `onSelected`로 대체한다 — 재클릭은 그 가드에서 막혀 `onSelected`가 안
                불리므로 동작은 그대로고, 홈에서는 다른 유형 클릭만 닫는다(홈 밖에서는 선택이 없어 어느 항목이든 홈으로 가며 닫힌다). */}
            <ContentTypeToggle variant="outline" onSelected={handleNavigate} />
          </div>

          <hr className={DIVIDER_CLASS} />

          {/* 알림 섹션은 로그인 사용자 전용이다 — `useNotificationListQuery`는 앱 전체에서 로그인
              상태에서만 마운트되는 컴포넌트 안에서만 호출된다(그 훅 자신의 문서화). 비로그인에서는
              행과 구분선을 통째로 건너뛴다. */}
          {me && (
            <>
              <NotificationDisclosure viewerId={me.id} onNavigate={handleNavigate} />
              <hr className={DIVIDER_CLASS} />
            </>
          )}

          <ul className="flex flex-col gap-0.5">
            {panelKeys.map((key) => (
              <li key={key}>
                <ProfileDestinationLink destinationKey={key} onClick={handleNavigate} className={SIDE_PANEL_NAV_ROW_CLASS} />
              </li>
            ))}
          </ul>

          <hr className={DIVIDER_CLASS} />

          <RecentChatsSection
            viewerId={me?.id}
            isSessionPending={isSessionPending}
            surface="popover"
            onNavigate={handleNavigate}
            className="mt-0"
          />

          <hr className={DIVIDER_CLASS} />

          {me ? (
            <>
              {/* 프로필 메뉴의 그룹(계정 · 고객센터)을 그룹 라벨 없이 구분선으로만 나눈다 — 드로어는 평면 목록이다. */}
              {PROFILE_MENU_DESTINATION_GROUPS.map((group) => (
                <Fragment key={group.label}>
                  <ul className="flex flex-col gap-0.5">
                    {group.keys
                      .filter((key) => isProfileDestinationVisible(key, me.enabledFeatures))
                      .map((key) => (
                        <li key={key}>
                          <ProfileDestinationLink
                            destinationKey={key}
                            me={me}
                            onClick={handleNavigate}
                            className={SIDE_PANEL_NAV_ROW_CLASS}
                          />
                        </li>
                      ))}
                  </ul>
                  <hr className={DIVIDER_CLASS} />
                </Fragment>
              ))}
              {/* 로그아웃은 `destructive`가 아니다 — `ProfileMenu`가 3단 근거(지우는 게 없고 다시 로그인하면
                  되돌아온다 / 앱의 다른 destructive 항목은 전부 데이터를 지운다 / `MyPagePage`의 로그아웃이
                  이미 `outline`)로 중립으로 정한 결정을 그대로 따른다. 비동기 액션이라 `aria-disabled` +
                  핸들러 첫 줄 early return을 쓴다(`disabled`는 클릭마다 blur를 일으켜 포커스가 사라진다 —
                  `apps/web/CLAUDE.md` 포커스 절). */}
              <button
                type="button"
                aria-disabled={logout.isPending}
                onClick={handleLogout}
                className={cn(SIDE_PANEL_NAV_ROW_CLASS, "aria-disabled:opacity-65")}
              >
                <LogOut aria-hidden />
                로그아웃
              </button>
            </>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {PUBLIC_MENU_DESTINATION_KEYS.map((key) => (
                <li key={key}>
                  <ProfileDestinationLink destinationKey={key} onClick={handleNavigate} className={SIDE_PANEL_NAV_ROW_CLASS} />
                </li>
              ))}
            </ul>
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

/** 개수가 아니라 점 하나, 색은 `bg-foreground`다. `bg-accent`(0.260)는 헤더 배경(0.160)
 * 대비 약 1.25:1로 베어 점으로 쓰면 안 보이고, `primary`는 무채색으로 충분한 신호에 이 시스템의 유일한
 * 유채색 예산을 쓰는 셈이라(One-Accent Rule) 기각했다 — `DESIGN.md` Status badges 절의 "사용자가 읽을 게
 * 생긴 상태만 밝기 천장 `text-foreground`로 올린다"(문의 `답변완료` 선례)와 같은 규범이다. 개수는 노출하지
 * 않는다(버거는 여러 항목의 수납구라 숫자를 달면 무엇의 개수인지 모호해진다) — 개수는 드로어 안
 * `NotificationDisclosure`가 진다. */
function BurgerButtonWithUnreadDot({ viewerId, className, ...props }: ComponentProps<typeof Button> & { viewerId: string }) {
  const hasUnread = (useNotificationUnreadCountQuery(viewerId).data?.unreadCount ?? 0) > 0;

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

/** 알림 벨은 `lg` 이상 헤더에만 있어, 그보다 좁은 화면에서는 여기서 알림을 연다. 시트 안에서 Radix
 * 드롭다운을 다시 열면 안 되므로(`apps/web/CLAUDE.md` 메뉴 · 모달 절) 인라인 disclosure로 편다. */
function NotificationDisclosure({ viewerId, onNavigate }: { viewerId: string; onNavigate: () => void }) {
  const listId = useId();
  const [isExpanded, setIsExpanded] = useState(false);
  const query = useNotificationListQuery(viewerId);
  const notifications = [...new Map((query.data?.pages.flatMap((page) => page.items) ?? []).map((item) => [item.id, item])).values()];
  const markAsRead = useMarkNotificationReadMutation(viewerId);
  const unreadCount = useNotificationUnreadCountQuery(viewerId).data?.unreadCount ?? 0;

  return (
    <>
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={listId}
        onClick={() => setIsExpanded((prev) => !prev)}
        className={cn(SIDE_PANEL_NAV_ROW_CLASS, "text-left")}
      >
        <Bell aria-hidden />
        <span className="flex-1">알림</span>
        {unreadCount > 0 && (
          // 채움이 아니라 윤곽이다 — 채움(`accent`)은 두 테마 모두 행 hover 채움 `secondary` 와 같은 값(0.26 / 0.93)이라 hover·
          // 포커스 때 알약이 사라졌다. `border` 윤곽은 시트(`popover`) 위 1.30 / 1.28, hover `secondary` 위 1.14 / 1.13 으로
          // 남는다(`DESIGN.md` Status badges 절의 중립 상태와 같은 처방). 읽을 게 생겼다는 표시라 글자는 밝기 천장이다.
          <span className="flex h-4 min-w-4 items-center justify-center rounded-full border border-border px-1 text-badge leading-none font-semibold text-foreground">
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
          {notifications.length === 0 && !query.isPending && !query.isError ? (
            <p className="px-2.5 py-4 text-center text-sm text-muted-foreground">아직 알림이 없어요.</p>
          ) : (
            notifications.map((notification) => (
              <NotificationDrawerItem
                key={notification.id}
                notification={notification}
                onRead={(id) => markAsRead.mutate(id)}
                onNavigate={onNavigate}
              />
            ))
          )}
          <NotificationFeedStatus isPending={query.isPending} hasError={query.isError} hasNext={!!query.hasNextPage} isFetchingNext={query.isFetchingNextPage}
            onRetry={() => { if (query.isFetchNextPageError) void query.fetchNextPage(); else void query.refetch(); }}
            onMore={() => void query.fetchNextPage()} />
        </div>
      )}
    </>
  );
}

// 드롭다운(`NotificationBell`)과 같은 의미: 목적지가 있는 공지·문의 답변은 이동 링크,
// 조치 통지 3종은 갈 곳이 없어 읽음 처리만 한다. 링크를 누르면 드로어의 다른 항목처럼 `onNavigate`로 시트를 닫는다.
function NotificationDrawerItem({
  notification,
  onRead,
  onNavigate,
}: {
  notification: NotificationResponse;
  onRead: (id: string) => void;
  onNavigate: () => void;
}) {
  const destination = resolveNotificationDestination(notification);
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);
  if (destination.kind === "comment") {
    return <Link to="/content/$type/$id" params={{ type: destination.contentType, id: destination.contentId }}
      search={{ comment: destination.commentId }} replace={modalState !== undefined} className={NOTIFICATION_ROW_CLASS}
      onClick={() => { if (!notification.read) onRead(notification.id); setModalState(undefined); onNavigate(); }}>
      <NotificationItemContent notification={notification} />
    </Link>;
  }

  if (destination.kind === "notice") {
    return (
      <Link
        to="/notices/$noticeId"
        params={{ noticeId: destination.noticeId }}
        onClick={() => {
          if (!notification.read) onRead(notification.id);
          onNavigate();
        }}
        className={NOTIFICATION_ROW_CLASS}
      >
        <NotificationItemContent notification={notification} />
      </Link>
    );
  }

  if (destination.kind === "inquiry") {
    return (
      <Link
        to="/inquiries/$inquiryId"
        params={{ inquiryId: destination.inquiryId }}
        onClick={() => {
          if (!notification.read) onRead(notification.id);
          onNavigate();
        }}
        className={NOTIFICATION_ROW_CLASS}
      >
        <NotificationItemContent notification={notification} />
      </Link>
    );
  }

  if (destination.kind === "cloverHistory") {
    return (
      <Link
        to="/clover/history"
        search={{ tab: "earn" }}
        onClick={() => {
          if (!notification.read) onRead(notification.id);
          onNavigate();
        }}
        className={NOTIFICATION_ROW_CLASS}
      >
        <NotificationItemContent notification={notification} />
      </Link>
    );
  }

  if (destination.kind === "none") {
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

  return assertNever(destination);
}
