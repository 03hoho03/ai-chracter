import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { CloverIcon } from "@/entities/clover";
import { useSessionQuery } from "@/entities/session";

import { BrandLogo } from "./BrandLogo";
import { ContentTypeToggle } from "./ContentTypeToggle";
import { MobileNavDrawer } from "./MobileNavDrawer";
import { NotificationBell } from "./NotificationBell";
import { ProfileMenu } from "./ProfileMenu";
import { SearchInlineExpand } from "./SearchInlineExpand";

/**
 * 로고 · 캐릭터/스토리 토글 · 이미지 · 클로버 · 검색 · 알림 벨 · 프로필로 고정 구성되며(클로버·알림·프로필은
 * 로그인 시에만, 비로그인은 그 자리에 로그인 버튼) 모든 화면에서 동일하게 노출된다(`routes/__root.tsx`에 마운트). 크롬은 항상 얇게 유지한다(DESIGN.md Overview 절).
 * 내부 바는 full-bleed다 — 전역 헤더는 뷰포트에 속하고 본문은 컬럼(`max-w-5xl`)에 속한다는 결정이며, 그 대가로
 * 로고 left와 본문 콘텐츠 left가 어긋난다(의도다).
 *
 * `sm`(640px) 미만은 [버거] · [로고 중앙] · [검색] 셋으로 축약한다. 한 DOM에 `grid grid-cols-[1fr_auto_1fr]
 * … sm:flex`를 써서 두 레이아웃을 만든다 — 마크업을 두 벌 두면 로고가 둘(접근가능한 홈 링크가 둘)이 되고
 * 검색이 두 벌이면 상태가 갈린다. `display:none` 자식은 grid 아이템을 만들지 않으므로 모바일에서
 * 버거=1열·로고=2열·우측 그룹=3열이 되고, `1fr auto 1fr`이라 버거와 검색의 폭이 달라도 로고가 정확히
 * 중앙이다. `sm:flex`에서는 `grid-template-columns`가 무효라 되돌리는 클래스가 필요 없다.
 * 텍스트 탭(이미지 링크 포함)·클로버·알림·프로필(비로그인은 로그인 버튼)은 `sm` 미만에서 `hidden`이지만 마운트는
 * 유지된다(알림 쿼리는 키가 같아 중복 요청이 안 난다) — 좌측 드로어(`MobileNavDrawer`)가 그 자리를 대신한다.
 */
export function Header() {
  const { data: me } = useSessionQuery();
  // `sm` 미만에서 검색이 펼쳐지면 버거·로고를 숨기고 검색이 헤더 한 줄을 독점한다. 펼침 상태 자체는
  // `SearchInlineExpand`가 계속 들고(자동 펼침 초기값·디바운스 등 자체 로직과 묶여 있어서), 이 값은
  // `onExpandedChange`로 전달받아 형제 엘리먼트(버거·로고)를 숨기는 데만 쓴다.
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background">
      {/* px-4 sm:px-6는 본문 컬럼과 같은 값을 유지한다 — 헤더를 px-6으로 올리면 390px에서 내부 폭이
          358→342px로 줄어 압박 지점에 들어간다(기존 실측). */}
      <div className="grid h-14 grid-cols-[1fr_auto_1fr] items-center gap-2 px-4 sm:flex sm:px-6">
        <MobileNavDrawer className={cn("justify-self-start", isSearchExpanded ? "hidden" : "sm:hidden")} />

        {/* 로고는 두 구성 모두에서 항상 노출된다(검색 독점 중인 sm 미만은 예외) — 워드마크 하나가 약 65px라
            숨겨서 아낄 폭이 거의 없다. 워드마크 SVG는 aria-hidden이라 링크 이름은 `aria-label`이 맡는다. `justify-self-center`는
            grid(모바일)에서만 의미가 있고 `sm:flex`에서는 무시된다. */}
        <Link
          to="/"
          aria-label="또나"
          className={cn(
            "inline-flex shrink-0 items-center justify-self-center rounded-md text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            isSearchExpanded && "max-sm:hidden",
          )}
        >
          <BrandLogo className="h-5 w-auto" />
        </Link>

        {/* 유형 토글과 "이미지" 링크는 `ContentTypeToggle`이 자기 flex 줄 하나로 묶어 내보낸다 — 이 래퍼는
            `sm` 미만 숨김만 맡는다. */}
        <div className="hidden sm:inline-flex">
          <ContentTypeToggle />
        </div>

        {/* min-w-0 — 아이콘 버튼은 모두 shrink-0이라, 폭이 모자랄 때 줄어들 수 있는 건 펼친 검색뿐이다.
            이 그룹이 기본값 min-width:auto면 그 축소가 막혀 헤더가 뷰포트를 넘는다(390px에서 실측).
            `justify-self-end`는 grid(모바일)에서 그룹을 우측에 붙이고, `sm:ml-auto`는 flex(데스크톱)에서
            같은 역할을 한다(justify-self는 flex 아이템에 효과가 없어 서로 간섭하지 않는다). 검색이
            헤더를 독점할 때는 이 그룹이 3열 전체를 차지해야 하므로 `max-sm:col-span-3` +
            `max-sm:justify-self-stretch`를 더한다. */}
        <div
          className={cn(
            "flex min-w-0 items-center gap-1 justify-self-end sm:ml-auto",
            isSearchExpanded && "max-sm:col-span-3 max-sm:justify-self-stretch",
          )}
        >
          {/* 클로버는 재화라 비로그인에게는 의미가 없고 누르면 로그인으로 튕기므로 알림·프로필처럼 로그인
              시에만 둔다. 검색 앞에 따로 분기해 DOM 순서 = 시각 순서 = Tab 순서를 유지한다. `sm` 미만에서는
              숨기고 좌측 드로어의 목적지 목록이 대신한다 — 빠뜨리면 이 버튼은 우측 그룹의 직접 자식이라
              검색 펼침 여부와 무관하게 모바일 헤더 우측에 검색과 나란히 항상 나타난다. `CloverIcon`은 자기 기본 크기 클래스(`size-3.5`)를
              갖고 있어 버튼의 svg 크기 규칙(`size-` 클래스가 없는 svg만 키운다)에서 빠지므로, 이웃 아이콘과
              같은 `size-4`를 여기서 명시한다. 초록은 그림 자체에만 있고 버튼은 다른 아이콘 버튼과 같은
              무채색 `ghost`다 — 유채색 hover를 더하지 않는다. */}
          {me && (
            <Button asChild variant="ghost" size="icon" aria-label="클로버" className="hidden sm:inline-flex">
              <Link to="/clover">
                <CloverIcon className="size-4" />
              </Link>
            </Button>
          )}
          <SearchInlineExpand onExpandedChange={setIsSearchExpanded} />
          {me ? (
            // `sm:contents` — NotificationBell·ProfileMenu는 이 슬라이스 밖에서 손댈 수 없는 트리거
            // 마크업을 갖고 있어(각각 아이콘 버튼) 개별 className을 주입할 수 없다. `display:contents`는
            // 이 wrapper를 박스 트리에서 지워 `sm` 이상에서 두 트리거가 원래처럼 우측 그룹의 직접 자식인
            // 것처럼 배치되게 하고, `hidden`은 `sm` 미만에서 통째로 감춘다 — 컴포넌트는 마운트된 채라
            // 알림 쿼리는 계속 캐시를 공유한다.
            <div className="hidden sm:contents">
              <NotificationBell viewerId={me.id} />
              <ProfileMenu me={me} />
            </div>
          ) : (
            <Button asChild size="sm" className="hidden sm:inline-flex">
              <Link to="/login">로그인</Link>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
