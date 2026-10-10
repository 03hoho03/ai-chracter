import { Button } from "@ai-character-chat/ui/components/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@ai-character-chat/ui/components/tooltip";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useRef, type ComponentProps, type MouseEvent, type ReactElement } from "react";

import { useSessionQuery } from "@/entities/session";

import { BrandLogo } from "./BrandLogo";
import { PROFILE_DESTINATION_LABEL, ProfileDestinationLink } from "./ProfileDestinationLink";
import { RecentChatsSection } from "./RecentChatsSection";
import { SIDE_PANEL_NAV_ROW_CLASS, SIDE_PANEL_ROW_CLASS } from "./sidePanelRowClass";
import { SIDE_PANEL_DESTINATION_KEYS, SIDE_PANEL_RAIL_CHATS_KEY } from "../model/profileDestinations";
import { isProfileDestinationVisible } from "../model/profileDestinationVisibility";

/** 패널의 DOM id. 드로어가 열린 채 창이 `lg` 이상으로 넓어지면 드로어가 닫히며 포커스를 이 패널의 현재 항목으로 보낸다. */
export const SIDE_PANEL_ID = "side-panel";

const LOGO_LINK_CLASS =
  "inline-flex shrink-0 items-center rounded-md text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50";

type SidePanelProps = {
  isCollapsed: boolean;
  /** 접힘이 사용자의 토글로 바뀌었을 때만 폭을 전환으로 움직인다(`useSidePanelCollapse`). */
  isToggled: boolean;
  onToggle: () => void;
};

/**
 * `lg` 이상의 좌측 패널. 펼침 240px(`w-60`) / 아이콘 레일 64px(`w-16`). 셸(`routes/__root.tsx`)이 `lg` 이상에서만
 * 마운트하고 접힘 상태도 셸이 든다.
 *
 * - 면은 헤더와 같은 `background` + 경계선 한 줄이고 정지 그림자가 없다. 패널 안에서 색을 가진 것은 최근 대화 썸네일뿐이다.
 * - `sticky top-0 h-dvh` — 스크롤 컨테이너는 window 하나다. `overflow-hidden` 은 패널 자신에만 걸어(폭 전환 중 글자를
 *   자른다) 자기 sticky 에 영향이 없다. 패널 안에서는 머리 아래 본문 하나만 스크롤한다 — 휠을 어디 굴려도 같은 것이
 *   움직인다. 그 본문의 안쪽 여백(펼침 8px·레일 12px)은 포커스 링(3px) + 아웃라인(1px)보다 넓어 끝 행의 링이 잘리지 않는다.
 * - 머리는 헤더와 같은 구조(바깥 `border-b` + 안쪽 `h-14`, 총 57px)라 두 아래 선이 같은 높이에서 한 줄로 이어진다.
 *   `h-14 border-b` 를 한 요소에 걸면 border-box 라 56px 가 되어 1px 어긋난다.
 * - 잉크(로고·내비 아이콘·썸네일·섹션 이름)는 x=24 에서 시작하고, 레일 아이콘 중심(32)도 펼침과 같아 접고 펼 때
 *   아이콘이 가로로 움직이지 않는다.
 * - 레일에서는 펼치기 버튼이 머리가 아니라 머리 바로 아래 첫 칸이다. 64px 머리에 심볼과 버튼을 나란히 두면 좌우 여백이
 *   4px 남짓이고, 심볼을 빼면 접힌 화면에 로고 홈 링크가 없어진다. Tab 순서는 두 상태 모두 로고 → 토글 → 내비다.
 * - 하단 고정 영역은 없다 — 프로필·클로버·알림은 헤더에 있다.
 */
export function SidePanel({ isCollapsed, isToggled, onToggle }: SidePanelProps) {
  const { data: me, isPending: isSessionPending } = useSessionQuery();
  const panelKeys = SIDE_PANEL_DESTINATION_KEYS.filter((key) => isProfileDestinationVisible(key, me?.enabledFeatures));
  // 토글을 누르면 그 버튼이 사라지고 다른 자리에 반대 버튼이 생긴다(머리 ↔ 레일 첫 칸). 키보드로 눌렀다면 포커스가
  // `<body>` 로 떨어지지 않게 새 버튼으로 옮긴다. 마우스로 눌렀을 때는 옮기지 않는다 — 옮기면 포인터와 무관한 자리에
  // 툴팁이 열린다.
  const shouldFocusToggleRef = useRef(false);
  const toggleRef = (node: HTMLButtonElement | null) => {
    if (node && shouldFocusToggleRef.current) {
      shouldFocusToggleRef.current = false;
      node.focus();
    }
  };
  const handleToggle = (event: MouseEvent<HTMLButtonElement>) => {
    // 키보드 Enter·Space 로 눌린 click 은 `detail` 이 0 이다. `:focus-visible` 만 보면 마우스로 포커스된 뒤 키보드로 누른
    // 경우를 놓친다.
    shouldFocusToggleRef.current = event.currentTarget.matches(":focus-visible") || event.detail === 0;
    onToggle();
  };

  return (
    // 레일 칸이 줄지어 있어 툴팁 하나를 본 뒤 이웃 칸으로 옮기면 지연 없이 바로 뜬다(Radix 의 건너뛰기 지연 300ms).
    <TooltipProvider delayDuration={300} skipDelayDuration={300}>
      <aside
        id={SIDE_PANEL_ID}
        aria-label="사이트 메뉴"
        className={cn(
          "sticky top-0 flex h-dvh shrink-0 flex-col overflow-hidden border-r border-border bg-background",
          isCollapsed ? "w-16" : "w-60",
          isToggled && "motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out",
        )}
      >
        <div className="shrink-0 border-b border-border">
          <div className={cn("flex h-14 items-center", isCollapsed ? "justify-center" : "justify-between pr-2 pl-6")}>
            <Link to="/" aria-label="또나" className={LOGO_LINK_CLASS}>
              <BrandLogo variant={isCollapsed ? "symbol" : "wordmark"} className="h-5 w-auto" />
            </Link>
            {!isCollapsed && (
              <RailTooltip label="사이드바 접기">
                <ToggleButton ref={toggleRef} isCollapsed={false} onClick={handleToggle} />
              </RailTooltip>
            )}
          </div>
        </div>

        <div className={cn("min-h-0 flex-1 overflow-y-auto", isCollapsed ? "px-3 py-2" : "p-2")}>
          {isCollapsed && (
            <div className="mb-2">
              <RailTooltip label="사이드바 펼치기">
                <ToggleButton ref={toggleRef} isCollapsed onClick={handleToggle} />
              </RailTooltip>
            </div>
          )}

          <nav aria-label="주 메뉴">
            <ul className="flex flex-col gap-0.5">
              {panelKeys.map((key) => (
                <li key={key}>
                  {isCollapsed ? (
                    <RailTooltip label={PROFILE_DESTINATION_LABEL[key]}>
                      <ProfileDestinationLink destinationKey={key} className={RAIL_ROW_CLASS} />
                    </RailTooltip>
                  ) : (
                    <ProfileDestinationLink destinationKey={key} className={SIDE_PANEL_NAV_ROW_CLASS} />
                  )}
                </li>
              ))}
            </ul>
            {/* 레일은 최근 대화를 숨기므로 전체 목록으로 가는 칸을 내비 아래 1px 선 뒤에 둔다(그룹 사이는 선 — admin 레일
                선례). 비로그인에게도 그린다: 누르면 로그인으로 갔다가 돌아오고, 이 칸이 없으면 비로그인 레일에서 대화
                목록으로 가는 길이 없다. */}
            {isCollapsed && (
              <>
                <div aria-hidden className="my-2 h-px bg-border" />
                <ul className="flex flex-col gap-0.5">
                  <li>
                    <RailTooltip label={PROFILE_DESTINATION_LABEL[SIDE_PANEL_RAIL_CHATS_KEY]}>
                      <ProfileDestinationLink destinationKey={SIDE_PANEL_RAIL_CHATS_KEY} className={RAIL_ROW_CLASS} />
                    </RailTooltip>
                  </li>
                </ul>
              </>
            )}
          </nav>

          {!isCollapsed && <RecentChatsSection viewerId={me?.id} isSessionPending={isSessionPending} surface="background" />}
        </div>
      </aside>
    </TooltipProvider>
  );
}

// 라벨은 접근 이름으로만 남는다(`sr-only`). 보이는 이름표는 툴팁이 진다.
const RAIL_ROW_CLASS = cn(SIDE_PANEL_ROW_CLASS, "size-10 justify-center [&_svg]:size-4 [&_svg]:shrink-0 [&>span]:sr-only");

type ToggleButtonProps = Omit<ComponentProps<"button">, "children"> & {
  isCollapsed: boolean;
};

/** 이름이 지금 할 동작을 말한다("사이드바 접기"/"사이드바 펼치기"). `aria-expanded`·`aria-pressed` 를 달지 않는다 —
 * 이름이 동작에 따라 바뀌는 버튼에 눌림 상태를 더하면 상태가 둘로 읽힌다. hover 채움은 내비 행과 같은 `secondary` 다
 * (같은 면 위의 hover 를 한 값으로). 툴팁 트리거가 `asChild` 로 얹는 핸들러를 받도록 나머지 props 를 버튼에 넘긴다. */
function ToggleButton({ isCollapsed, ...rest }: ToggleButtonProps) {
  const label = isCollapsed ? "사이드바 펼치기" : "사이드바 접기";

  return (
    <Button
      type="button"
      variant="ghost"
      size={isCollapsed ? "icon-lg" : "icon-sm"}
      aria-label={label}
      className="hover:bg-secondary"
      {...rest}
    >
      {isCollapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
    </Button>
  );
}

/** 아이콘만 보이는 칸의 이름표. 툴팁 글자가 트리거의 접근 이름과 같아 Radix 의 설명 연결(`aria-describedby`)을 끊고
 * 떠 있는 글자도 접근성 트리에서 뺀다 — 그대로 두면 스크린리더가 같은 이름을 두 번 읽는다. 마우스 hover 와 키보드
 * 포커스 모두에서 뜬다(`title` 은 키보드 포커스에 뜨지 않는다). */
function RailTooltip({ label, children }: { label: string; children: ReactElement }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild aria-describedby={undefined}>
        {children}
      </TooltipTrigger>
      <TooltipContent side="right" aria-hidden>
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
