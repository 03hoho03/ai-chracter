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
 * `routes/__root.tsx`에 마운트되고, 헤더를 그리지 않는 화면은 `isGlobalHeaderHidden`이 정한다. 크롬은 항상 얇게
 * 유지한다(DESIGN.md Overview 절). 구성은 경계 `lg`(1024px)에서 둘로 갈린다:
 *
 * - `lg` 이상: 헤더가 좌측 패널 오른쪽 열에 놓이고, 캐릭터/스토리 토글 · 노벨(노벨이 열려 있을 때) … 클로버 · 검색 · 알림 벨 ·
 *   프로필이다(클로버·알림·프로필은 로그인 시에만, 비로그인은 그 자리에 로그인 버튼). 로고는 패널 머리에 있어 헤더의
 *   로고는 `lg:hidden`이다.
 * - `lg` 미만: [버거] · [로고 중앙] · [검색] 셋이다. 그 폭에는 패널이 없어, 유형 전환·클로버·알림·프로필 메뉴의 목적지는
 *   패널 내용과 함께 좌측 드로어(`MobileNavDrawer`)가 담는다. 그 넷은 `hidden`이지만 마운트는 유지된다(알림 쿼리는 키가
 *   같아 중복 요청이 안 난다).
 *
 * 한 DOM에 `grid grid-cols-[1fr_auto_1fr] … lg:flex`를 써서 두 레이아웃을 만든다 — 마크업을 두 벌 두면 로고가 둘(접근가능한
 * 홈 링크가 둘)이 되고 검색이 두 벌이면 상태가 갈린다. `display:none` 자식은 grid 아이템을 만들지 않으므로 좁은 폭에서
 * 버거=1열·로고=2열·우측 그룹=3열이 되고, `1fr auto 1fr`이라 버거와 검색의 폭이 달라도 로고가 정확히
 * 중앙이다. `lg:flex`에서는 `grid-template-columns`가 무효라 되돌리는 클래스가 필요 없다.
 */
export function Header() {
  const { data: me } = useSessionQuery();
  // `sm`(640px) 미만에서 검색이 펼쳐지면 버거·로고를 숨기고 검색이 헤더 한 줄을 독점한다. 640~1023px 에서는 펼쳐도
  // 버거·로고가 남고 입력칸이 3열 안에 든다 — 그 폭에서 버거를 숨기면 검색하는 동안 드로어에 닿을 길이 없다. 펼침 상태 자체는
  // `SearchInlineExpand`가 계속 들고(자동 펼침 초기값·디바운스 등 자체 로직과 묶여 있어서), 이 값은
  // `onExpandedChange`로 전달받아 형제 엘리먼트(버거·로고)를 숨기는 데만 쓴다.
  const [isSearchExpanded, setIsSearchExpanded] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background">
      {/* px-4 sm:px-6는 본문 컬럼과 같은 값을 유지한다 — 헤더를 px-6으로 올리면 390px에서 내부 폭이
          358→342px로 줄어 압박 지점에 들어간다(기존 실측). */}
      <div className="grid h-14 grid-cols-[1fr_auto_1fr] items-center gap-2 px-4 sm:px-6 lg:flex">
        <MobileNavDrawer className={cn("justify-self-start lg:hidden", isSearchExpanded && "max-sm:hidden")} />

        {/* 로고는 `lg` 미만에서 늘 중앙에 있다(검색 독점 중인 `sm` 미만은 예외) — 워드마크 하나가 약 65px라
            숨겨서 아낄 폭이 거의 없다. `lg` 이상에서는 좌측 패널 머리에 로고가 있어 여기서는 `lg:hidden` 이다 — 화면에
            로고 홈 링크는 하나다(`display:none` 이라 접근성 트리에서도 빠진다. 패널 마운트 판정이 같은 `64rem` 경계다).
            워드마크 SVG는 aria-hidden이라 링크 이름은 `aria-label`이 맡는다. `justify-self-center`는
            grid(`lg` 미만)에서만 의미가 있고 `lg:flex`에서는 무시된다. */}
        <Link
          to="/"
          aria-label="또나"
          className={cn(
            "inline-flex shrink-0 items-center justify-self-center rounded-md text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            isSearchExpanded && "max-sm:hidden",
            "lg:hidden",
          )}
        >
          <BrandLogo className="h-5 w-auto" />
        </Link>

        {/* 유형 토글과 "노벨" 링크는 `ContentTypeToggle`이 자기 flex 줄 하나로 묶어 내보낸다 — 이 래퍼는 `lg` 미만 숨김과
            `-ml-2` 만 맡는다. `-ml-2` 는 탭의 좌우 패딩(`px-2`)만큼 당겨 첫 글자를 헤더 거터(패널 경계 + 24px)에 맞춘다 — 홈 첫
            행 토글과 같은 처방이고, 본문 컬럼이 영역을 다 채우는 폭에서는 본문 왼쪽 선과 같은 x 가 된다. */}
        <div className="hidden lg:-ml-2 lg:inline-flex">
          <ContentTypeToggle />
        </div>

        {/* min-w-0 — 아이콘 버튼은 모두 shrink-0이라, 폭이 모자랄 때 줄어들 수 있는 건 펼친 검색뿐이다.
            이 그룹이 기본값 min-width:auto면 그 축소가 막혀 헤더가 뷰포트를 넘는다(390px에서 실측).
            `justify-self-end`는 grid(`lg` 미만)에서 그룹을 우측에 붙이고, `lg:ml-auto`는 flex(`lg` 이상)에서
            같은 역할을 한다(justify-self는 flex 아이템에 효과가 없어 서로 간섭하지 않는다). 검색이
            헤더를 독점할 때(`sm` 미만)는 이 그룹이 3열 전체를 차지해야 하므로 `col-span-3` + `justify-self-stretch`를
            더한다 — 640~1023px 도 grid 라 `max-sm:`로 좁히지 않으면 그 폭에서 버거·로고와 한 행을 다투다 줄이 깨진다. */}
        <div
          className={cn(
            "flex min-w-0 items-center gap-1 justify-self-end lg:ml-auto",
            isSearchExpanded && "max-sm:col-span-3 max-sm:justify-self-stretch",
          )}
        >
          {/* 클로버는 재화라 비로그인에게는 의미가 없고 누르면 로그인으로 튕기므로 알림·프로필처럼 로그인
              시에만 둔다. 검색 앞에 따로 분기해 DOM 순서 = 시각 순서 = Tab 순서를 유지한다. `lg` 미만에서는
              숨기고 좌측 드로어의 목적지 목록이 대신한다 — 빠뜨리면 이 버튼은 우측 그룹의 직접 자식이라
              검색 펼침 여부와 무관하게 좁은 헤더 우측에 검색과 나란히 항상 나타난다. `CloverIcon`은 자기 기본 크기 클래스(`size-3.5`)를
              갖고 있어 버튼의 svg 크기 규칙(`size-` 클래스가 없는 svg만 키운다)에서 빠지므로, 이웃 아이콘과
              같은 `size-4`를 여기서 명시한다. 초록은 그림 자체에만 있고 버튼은 다른 아이콘 버튼과 같은
              무채색 `ghost`다 — 유채색 hover를 더하지 않는다. */}
          {me && (
            <Button asChild variant="ghost" size="icon" aria-label="클로버" className="hidden lg:inline-flex">
              <Link to="/clover">
                <CloverIcon className="size-4" />
              </Link>
            </Button>
          )}
          <SearchInlineExpand onExpandedChange={setIsSearchExpanded} />
          {me ? (
            // `lg:contents` — NotificationBell·ProfileMenu는 트리거 마크업을 자기 안에 갖고 있어(각각 아이콘 버튼)
            // 개별 className을 주입할 수 없다. `display:contents`는
            // 이 wrapper를 박스 트리에서 지워 `lg` 이상에서 두 트리거가 원래처럼 우측 그룹의 직접 자식인
            // 것처럼 배치되게 하고, `hidden`은 `lg` 미만에서 통째로 감춘다 — 컴포넌트는 마운트된 채라
            // 알림 쿼리는 계속 캐시를 공유한다.
            <div className="hidden lg:contents">
              <NotificationBell viewerId={me.id} />
              <ProfileMenu me={me} />
            </div>
          ) : (
            <Button asChild size="sm" className="hidden lg:inline-flex">
              <Link to="/login">로그인</Link>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
