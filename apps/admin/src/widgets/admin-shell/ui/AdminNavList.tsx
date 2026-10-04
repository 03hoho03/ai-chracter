import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouterState } from "@tanstack/react-router";
import { useId } from "react";

import { ADMIN_NAV_GROUPS, type AdminNavGroup, type AdminNavItem, type AdminNavTo } from "../config/nav";
import { resolveActiveNavTo } from "../lib/resolveActiveNavTo";

// 테두리 없는 ghost 행. hover 와 활성 채움은 같은 `secondary`(사이드바 `card`·드로어 `popover` 위에서 `muted` 는
// 같은 값이라 사라진다)이고, 활성은 `font-semibold` + 왼쪽 `primary` 막대로 갈린다. 포커스는 보더 없는 컨트롤
// 레시피 — 3:1 을 지는 불투명 1px 아웃라인 + 50% 링. `outline-none` 을 함께 두면 아웃라인 스타일 변수가 none 으로
// 남아 포커스 때도 아웃라인이 그려지지 않으므로 쓰지 않는다. 손가락 포인터 40px 는 프리미티브가 아니라 이 행이
// 진다(admin 전용 CSS 는 프리미티브 data-slot 만 본다).
const NAV_ROW_CLASS = cn(
  "relative flex h-9 items-center gap-3 rounded-lg px-3 text-sm font-medium whitespace-nowrap text-foreground",
  "motion-safe:transition-colors hover:bg-secondary",
  "focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring",
  "pointer-coarse:min-h-10",
  "[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
  "aria-[current=page]:bg-secondary aria-[current=page]:font-semibold",
  "aria-[current=page]:before:absolute aria-[current=page]:before:inset-y-2 aria-[current=page]:before:left-0 aria-[current=page]:before:w-0.5 aria-[current=page]:before:rounded-full aria-[current=page]:before:bg-primary",
);

type AdminNavListProps = {
  /** 아이콘 레일로 그린다(라벨·그룹 이름은 스크린리더에만). 드로어는 늘 펼친 모양이다. */
  isCollapsed?: boolean;
  /** 항목을 눌렀을 때 — 드로어가 닫는 데 쓴다. */
  onNavigate?: () => void;
};

/** 사이드바와 드로어가 함께 쓰는 내비 목록 한 벌. 그룹 이름 id 는 `useId` 라 두 자리에 동시에 있어도 겹치지 않는다. */
export function AdminNavList({ isCollapsed = false, onNavigate }: AdminNavListProps) {
  const activeTo = useRouterState({ select: (state) => resolveActiveNavTo(state.location) });

  return (
    <nav aria-label="관리 메뉴" className={cn("min-h-0 flex-1 overflow-y-auto pb-2", isCollapsed ? "px-2" : "px-3")}>
      {ADMIN_NAV_GROUPS.map((group, index) => (
        <NavGroup
          key={group.label}
          group={group}
          isFirst={index === 0}
          isCollapsed={isCollapsed}
          activeTo={activeTo}
          onNavigate={onNavigate}
        />
      ))}
    </nav>
  );
}

type NavGroupProps = {
  group: AdminNavGroup;
  isFirst: boolean;
  isCollapsed: boolean;
  activeTo: AdminNavTo | null;
  onNavigate?: () => void;
};

function NavGroup({ group, isFirst, isCollapsed, activeTo, onNavigate }: NavGroupProps) {
  const labelId = useId();

  return (
    // 레일에서는 그룹 이름이 안 보이므로 그룹 사이를 1px 선으로 나눈다.
    <div className={cn(isCollapsed && (isFirst ? "pt-2" : "mt-2 border-t border-border pt-2"))}>
      <p id={labelId} className={isCollapsed ? "sr-only" : "px-3 pt-4 pb-1 text-xs font-medium text-muted-foreground"}>
        {group.label}
      </p>
      <ul aria-labelledby={labelId} className="flex flex-col gap-0.5">
        {group.items.map((item) => (
          <li key={item.to}>
            <NavRow item={item} isActive={item.to === activeTo} isCollapsed={isCollapsed} onNavigate={onNavigate} />
          </li>
        ))}
      </ul>
    </div>
  );
}

type NavRowProps = {
  item: AdminNavItem;
  isActive: boolean;
  isCollapsed: boolean;
  onNavigate?: () => void;
};

function NavRow({ item, isActive, isCollapsed, onNavigate }: NavRowProps) {
  const Icon = item.icon;

  return (
    // `Link` 는 자기 활성 판정의 `aria-current="page"` 를 props 맨 끝에 덮어쓴다. 기본(접두 일치)으로 두면 유저별
    // 생성 이미지 화면에서 "유저 관리" 링크가 스스로 현재가 되어 우리가 단 "이미지 생성 관리"와 둘이 동시에
    // 현재가 된다 — 그래서 `Link` 의 판정은 "정확히 같은 경로"로 좁히고(그 경우는 위 판정과 늘 일치한다) 하위
    // 경로의 활성은 직접 단다.
    <Link
      to={item.to}
      activeOptions={{ exact: true, includeSearch: false }}
      aria-current={isActive ? "page" : undefined}
      title={isCollapsed ? item.label : undefined}
      onClick={onNavigate}
      className={cn(NAV_ROW_CLASS, isCollapsed && "h-10 w-full justify-center px-0")}
    >
      <Icon aria-hidden />
      <span className={isCollapsed ? "sr-only" : "truncate"}>{item.label}</span>
    </Link>
  );
}
