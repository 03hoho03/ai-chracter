import { Button } from "@ai-character-chat/ui/components/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@ai-character-chat/ui/components/sheet";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { MAIN_CONTENT_ID } from "@/shared/config/landmarks";
import { useIsDesktopLayout } from "@/shared/lib/useMediaQuery";

export type DetailActionsHost = {
  /** 조치가 성공하면 패널이 부른다. `lg` 미만이면 시트를 닫아 포커스가 하단 바 버튼으로 돌아간다. */
  onDone: () => void;
};

export type DetailActions = {
  /** 조치 열·시트의 제목("신고 처리"). */
  title: string;
  /** 하단 바 버튼("처리하기"). */
  triggerLabel: string;
  /** 하단 바 왼쪽 한 줄 요약("대기 중인 신고"). */
  summary?: ReactNode;
  render: (host: DetailActionsHost) => ReactNode;
};

type DetailLayoutProps = {
  children: ReactNode;
  /** `null` 이면 조치가 없는 상세다 — 조치 열·하단 바·여백을 아무것도 그리지 않는다. 판정은 호출부가 한다. */
  actions: DetailActions | null;
};

/**
 * 상세 화면의 본문 + 조치. `lg` 이상은 본문 오른쪽 sticky 조치 열, 미만은 하단 고정 바 → 바텀시트.
 *
 * **조치 패널은 한 번만 마운트한다.** 패널은 RHF 폼이라 열·시트에 두 벌 그리면 폼과 정적 id 가 둘이 되고, 시트 안에만
 * 그리면 시트를 닫을 때 언마운트돼 고른 처리·적던 사유가 사라진다. 그래서 패널을 이 컴포넌트가 만든 DOM 노드 하나에
 * 포털로 그려 두고, 그 노드만 조치 열이나 열린 시트 안으로 옮겨 붙인다 — React 쪽에서는 늘 같은 자리에 마운트돼
 * 있어 입력이 시트를 닫았다 열어도, 창 폭이 `lg` 를 넘나들어도 남는다.
 *
 * 패널의 React 부모는 시트가 아니라 이 컴포넌트인데도 시트 안에서 그대로 동작한다. 포커스 트랩·Esc·스크롤 잠금은
 * DOM 포함 관계로 판정하고, 시트의 "바깥 누르기"·Tab 순환처럼 React 이벤트로 판정하는 것도 React 가 DOM 안에 끼워
 * 넣은 포털의 이벤트를 그 DOM 조상(시트 콘텐츠) 쪽으로도 한 번 더 보내 줘서 시트가 받는다 — 시트 포털이 React 가 듣는
 * `body` 에 붙어 있어서다(React 19 `dispatchEventForPluginEventSystem`). 패널 안 라디오·입력칸을 눌러도 시트가 닫히지
 * 않고 Tab·Shift+Tab 이 시트 안에서 돈다(실측).
 */
export function DetailLayout({ children, actions }: DetailLayoutProps) {
  const isDesktop = useIsDesktopLayout();
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [portalNode] = useState(() => {
    const node = document.createElement("div");
    node.className = "flex min-w-0 flex-col gap-4";
    return node;
  });
  const adopt = useCallback(
    (slot: HTMLDivElement | null) => {
      slot?.appendChild(portalNode);
    },
    [portalNode],
  );

  // 시트를 연 채 `lg` 이상으로 넓히면 하단 바가 사라진다 — 넓어지는 순간 닫고 패널은 조치 열로 옮겨 간다.
  if (isDesktop && isSheetOpen) setIsSheetOpen(false);

  useFocusMainWhenActionsDisappear(actions !== null);

  // 본문·조치 열·하단 바·패널 포털의 자리를 분기마다 같게 둔다 — 자리가 바뀌면 React 가 그 아래를 다시 마운트해
  // 창 폭이 `lg` 를 넘을 때 패널 입력과 본문 상태가 사라진다.
  const hasAside = actions !== null && isDesktop;
  const hasBar = actions !== null && !isDesktop;

  // 조치 열이 있으면 본문 열은 상한 없이 남는 폭을 다 받는다 — 바깥 `PageContainer` 상한(`max-w-6xl`)에서 조치 열을 빼면
  // 본문은 최대 792px 라 줄 길이는 이미 그 상한이 묶는다. 본문 열에 따로 상한을 두면 넓은 화면에서 오른쪽이 비는 동안
  // 밀집 표(유저 상세의 채팅방·조치 이력)가 가로로 스크롤됐다. 조치 열이 없는 상세(문의 답변·공지 편집·열람 화면)는
  // 글과 폼이 본문이라 `max-w-3xl` 로 줄 길이를 묶는다.
  return (
    <div
      className={
        hasAside
          ? "grid grid-cols-[minmax(0,1fr)_var(--container-2xs)] items-start gap-6"
          : "flex max-w-3xl min-w-0 flex-col gap-6"
      }
    >
      {/* 본문 열 폭은 조치 열 유무·사이드바 접힘에 따라 바뀌어, 안쪽 그리드는 뷰포트가 아니라 이 열 폭(`@container`)으로 가른다. */}
      <div className="@container flex min-w-0 flex-col gap-6">
        {children}
        {/* 하단 바 높이만큼 비워 본문 마지막 요소가 바 뒤에 깔리지 않게 한다. */}
        {hasBar && <div aria-hidden className="h-(--admin-action-bar-height) shrink-0" />}
      </div>

      {hasAside && (
        <aside
          aria-labelledby="detail-actions-title"
          className="sticky top-6 flex max-h-[calc(100dvh-3rem)] flex-col gap-4 overflow-y-auto rounded-xl border border-border bg-card p-4"
        >
          <h2 id="detail-actions-title" className="text-lg font-semibold text-foreground">
            {actions.title}
          </h2>
          <div ref={adopt} />
        </aside>
      )}

      {hasBar && (
        <div
          data-admin-action-bar
          className="fixed inset-x-0 bottom-0 z-20 h-(--admin-action-bar-height) border-t border-border bg-background pb-[env(safe-area-inset-bottom)]"
        >
          <div className="flex h-full items-center gap-3 px-4">
            <div className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{actions.summary}</div>
            <Sheet open={isSheetOpen} onOpenChange={setIsSheetOpen}>
              <SheetTrigger asChild>
                <Button type="button">{actions.triggerLabel}</Button>
              </SheetTrigger>
              <SheetContent
                side="bottom"
                aria-describedby={undefined}
                className="max-h-below-header gap-0 rounded-t-xl"
                // 위 재전달이 있어 지금은 불리지 않지만, 패널을 누른 것이 바깥 누르기로 잡히면 시트가 닫히며 그 클릭이
                // "처리 확정"에도 닿는다 — 이벤트 경로가 바뀌어도 그 일이 없게 노드 안 누르기는 여기서도 막는다.
                onInteractOutside={(event) => {
                  if (event.target instanceof Node && portalNode.contains(event.target)) event.preventDefault();
                }}
              >
                <SheetHeader className="shrink-0 pr-14">
                  <SheetTitle className="font-semibold">{actions.title}</SheetTitle>
                </SheetHeader>
                <div ref={adopt} className="min-h-0 overflow-y-auto px-4 pb-4-safe" />
              </SheetContent>
            </Sheet>
          </div>
        </div>
      )}

      {actions !== null &&
        createPortal(actions.render({ onDone: () => setIsSheetOpen(false) }), portalNode)}
    </div>
  );
}

/**
 * 조치가 성공해 더 할 조치가 없어지면(신고 처리 완료 등) 조치 열·하단 바가 통째로 사라지고, 그 안에 있던 포커스는
 * `<body>` 로 떨어진다. 그 전이를 아는 곳이 여기뿐이라, 그때 포커스를 잃었으면 본문으로 보낸다.
 */
function useFocusMainWhenActionsDisappear(hasActions: boolean) {
  const hadActionsRef = useRef(hasActions);
  useEffect(() => {
    const hadActions = hadActionsRef.current;
    hadActionsRef.current = hasActions;
    if (!hadActions || hasActions) return;
    if (document.activeElement && document.activeElement !== document.body) return;
    document.getElementById(MAIN_CONTENT_ID)?.focus();
  }, [hasActions]);
}
