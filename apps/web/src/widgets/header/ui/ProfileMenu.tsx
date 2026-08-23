import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  ImagePlus,
  LayoutGrid,
  LogOut,
  MessagesSquare,
  Plus,
  Settings2,
  Star,
  User,
} from "lucide-react";
import { useId, type ReactNode } from "react";
import { toast } from "sonner";

import type { MeResponse } from "@/entities/session";
import { useLogoutMutation } from "@/features/logout";

/** prd-creator-entry-and-my-works.md US-012 — 창작 / 활동 / 계정 세 그룹 + 로그아웃.
 *
 * 최상단이 `작품 만들기`인 건 FR-13이 정한 세 진입점(`/my` 상단 · `/my` 빈 상태 · 여기) 중 **화면과
 * 무관하게 항상 닿는 유일한 자리**라서다. 헤더에는 만들기를 더하지 않는다(FR-14) — 크롬은 h-14 한 줄뿐이고
 * 이미 아이콘 넷이 앉아 있다.
 *
 * 미구현 기능(구독함·활동배지·차단관리·크리에이터·혜택)은 넣지 않는다(결정 11). 그래서 항목이 8개로
 * 유지되고 390×844에서 스크롤 없이 들어간다.
 */
export function ProfileMenu({ me }: { me: MeResponse }) {
  const navigate = useNavigate();
  const logout = useLogoutMutation();

  const handleLogout = () => {
    logout.mutate(undefined, {
      onSuccess: () => {
        toast.success("로그아웃되었어요.");
        void navigate({ to: "/" });
      },
      onError: () => {
        toast.error("로그아웃에 실패했어요. 잠시 후 다시 시도해주세요.");
      },
    });
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {/* `계정 메뉴`가 아니라 `메뉴`다 — 여덟 항목 중 일곱이 목적지고 첫 그룹이 `창작`이라, 스크린리더가
            "계정 메뉴"를 읽고 연 다음 첫 announce가 `그룹 창작 · 작품 만들기`가 되면 이름과 내용이 어긋난다.
            눈으로 보는 사용자에겐 안 보이는 자리라 이 어긋남은 AT 사용자만 겪는다. */}
        <Button type="button" variant="ghost" size="icon" aria-label={`${me.nickname}님 메뉴`}>
          <User aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      {/* 그룹 경계마다 구분선을 둔다 — **라벨만으로는 경계가 픽셀상 표시되지 않기 때문이다.**
          한때 구분선을 둘(신원 블록 아래 / 로그아웃 위)만 두고 "라벨이 이미 경계를 그으니 중복"이라고
          적어 뒀는데, 재보니 거짓이었다. `DropdownMenuContent`에 flex도 gap도 없어 행 박스가 그대로
          맞닿고(인접 행 `top - bottom` 전부 **0.00px** 실측), 패딩은 `py-1`로 박스 **안**에 있다. 그래서
          `이미지 생성`(창작 마지막) ↔ `활동` 라벨의 광학 간격이 4+4=**8px**인데 같은 그룹 안
          `작품 만들기` ↔ `내 작품`도 4+4=**8px**로 **완전히 같다**. 근접성 축이 경계에 기여하는 게 0이라
          유사성 축(12px/500/muted vs 14px/400/foreground) 혼자 일하고 있었다. 이 저장소는 이미
          `apps/web/CLAUDE.md`에서 필터 축 간격 1.5배를 Gestalt 임계 미달로 판정했다 — 여기는 1.0배였다.
          높이 비용은 18px(350→368)이다. 세로 390×844에서는 `max-h` 796px 대비 **여유 428px**로 무해하다.
          **가로로 눕힌 폰(844×390)에서는 대가가 있고, 그건 이 결정이 만든 회귀다** — 프리미티브의
          `max-h-(--radix-…-available-height)`가 342px로 자르는데, 구분선 둘일 때는 넘치는 8px이 `로그아웃`
          **아래 여백**이라 글자가 16/16px 온전히 보였고, 넷일 때는 넘치는 26px이 `로그아웃` **행 자체**라
          글자가 **0/16px**로 한 픽셀도 안 보인다(행 박스도 6/28px, `scrollTop: 0` 실측 A/B).
          `overflow-y-auto`라 스크롤·End로 닿지만 macOS 오버레이 스크롤바에는 상시 표시가 없어 **포인터·터치
          사용자에게는 잘렸다는 신호가 아예 없다** — 메뉴가 구분선에서 끊겨 완결돼 보인다.
          그래도 구분선을 되돌리지 않는다: 위의 1.0배 결함은 **모든 폭·모든 기기에서 항상** 켜져 있는 반면
          이건 가로 폰 한 곳이고 스크롤·키보드라는 탈출구가 있다. 잘림을 **보이게** 만드는 건 `overflow-y-auto`를
          쥔 프리미티브 소관이라 `packages/ui/CLAUDE.md`의 dropdown 일괄 항목에 등재해 뒀다.
          뷰포트를 **넘어가는** 일은 이 프리미티브에서 구조적으로 불가능하다(잘릴 뿐이다). */}
      <DropdownMenuContent align="end" className="w-56">
        {/* 닉네임은 그룹 이름이 아니라 "누구의 메뉴인가"다. 기본 Label 스타일(text-xs muted)을 그대로 두면
            바로 아래 `창작`과 글자 크기·색이 같아 넷째 그룹 라벨로 읽힌다. 반대로 크기만 올리면 이번엔
            항목(14px/400/foreground)과 한 웨이트 차이밖에 안 나 아이콘 없는 비활성 항목으로 읽힌다.
            실측 세 값은 라벨 12px/500/oklch(0.68) · 항목 14px/400/oklch(0.93) · 여기 14px/600/oklch(0.93)이라
            **항목과는 웨이트(400↔600)가, 라벨과는 크기(12↔14)와 색(muted↔foreground)이** 가른다 —
            라벨과의 웨이트 차는 한 단계뿐이니 크기나 색을 건드리면 이 분리가 무너진다. 높이 비용은 0이다.
            **이 사다리는 메뉴 안에 600이 여기 하나일 때만 성립한다** — 현재 페이지를 `font-semibold`로
            표시하는 코드가 잠깐 있었는데, 활성 항목이 14px/600/oklch(0.93)으로 이 행과 세 값이 전부 같아져
            메뉴에 제목이 둘로 읽혔다(메뉴가 가리킬 수 있는 7개 라우트 전부에서). 지웠다. */}
        <DropdownMenuLabel className="truncate text-sm font-semibold text-foreground">
          {me.nickname}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />

        <ProfileMenuGroup label="창작">
          <DropdownMenuItem asChild>
            <Link to="/builder">
              <Plus aria-hidden />
              작품 만들기
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to="/my">
              <LayoutGrid aria-hidden />
              내 작품
            </Link>
          </DropdownMenuItem>
          {/* 헤더의 이미지 생성 버튼과 **같은 글리프**를 쓴다 — 같은 목적지에 다른 아이콘을 붙이면
              둘이 다른 기능으로 읽힌다. */}
          <DropdownMenuItem asChild>
            <Link to="/studio/images">
              <ImagePlus aria-hidden />
              이미지 생성
            </Link>
          </DropdownMenuItem>
        </ProfileMenuGroup>
        <DropdownMenuSeparator />

        <ProfileMenuGroup label="활동">
          <DropdownMenuItem asChild>
            <Link to="/chats">
              <MessagesSquare aria-hidden />
              내 채팅목록
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to="/favorites">
              <Star aria-hidden />
              즐겨찾기
            </Link>
          </DropdownMenuItem>
        </ProfileMenuGroup>
        <DropdownMenuSeparator />

        <ProfileMenuGroup label="계정">
          <DropdownMenuItem asChild>
            <Link to="/profile/$userId" params={{ userId: me.id }}>
              <User aria-hidden />
              내 프로필
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to="/mypage">
              <Settings2 aria-hidden />
              마이페이지 · 설정
            </Link>
          </DropdownMenuItem>
        </ProfileMenuGroup>

        <DropdownMenuSeparator />

        {/* `variant="destructive"`를 쓰지 않는다. DESIGN.md §Destructive가 이 토큰의 뜻을 삭제·탈퇴·거부·
            이용제한 넷으로 못박았는데 로그아웃은 넷 중 아무것도 아니다(지우는 게 없고 다시 로그인하면 되돌아온다).
            앱의 나머지 `DropdownMenuItem variant="destructive"`는 3파일 4항목이고 전부 사용자 데이터를
            지운다(`MyWorkCardMenu`의 `삭제하기`·`편집한 내용 버리기`, `ChatRoomListItemRow`, `MessageBubble`
            — 글리프는 `Trash2` 셋에 `RotateCcw` 하나다) — 여기만 예외로 두면 그 신호가 묽어진다.
            대비도 이쪽이 낫다: destructive 행은 focus에서 `bg-destructive/10`이 얹혀 텍스트가 다크 4.3492 /
            라이트 4.2176으로 AA 미달인데(rest 4.8359/4.8914에서 떨어진다), 중립 행은 focus에서 12.6689/14.0576다.
            Radix는 `pointermove`에도 focus를 걸므로 이건 키보드 사용자만의 상태가 아니다.
            셋째, 앱의 **다른** 로그아웃 자리(`MyPagePage`)가 이미 `Button variant="outline"`(중립)이라 이 변경이
            두 자리의 시각 언어를 일치시킨다.
            심각도는 색이 아니라 아이콘(`LogOut`)과 구분선이 진다 — `MyWorkCardMenu`가 쓴 것과 같은 규칙이다.

            `event.preventDefault()`가 있어야 옆의 `disabled`가 살아난다 — Radix의 기본 `onSelect`는 메뉴를
            닫으므로, 막지 않으면 `logout.isPending`이 true인 동안 이 행은 이미 언마운트돼 있다(실측: 선택
            직후 `[data-slot=dropdown-menu-content]`가 `null`). 그래서 (1) 진행 표시가 죽은 코드였고
            (2) 실패했을 때 재시도가 "메뉴 다시 열기 + 항목 고르기" 두 동작이 됐다. **(2)를 "다시 누를 자리가
            화면에 없었다"고 적어 뒀던 건 거짓이다** — 실패하면 세션이 그대로라 `Header`가 계속 이 컴포넌트를
            렌더하므로 트리거는 sticky 헤더의 같은 자리에 남는다. 사라지는 건 자리가 아니라 그 행이다.
            실패 경로는 요청을 막아 실측했다 — 메뉴가 열린 채 토스트가 뜬다. 성공하면 `resetQueries`가
            세션을 비우면서 `ProfileMenu` 자체가 언마운트되므로 메뉴는 그대로 닫힌다(양쪽 다 실측).
            대가 하나: 메뉴가 modal이라 열려 있는 동안 `body`가 `pointer-events: none`이라 토스트를 클릭으로
            닫을 수 없다(실측). 액션 버튼이 없고 자동 소멸하므로 실질 피해는 없다. **`aria-live`는 억제되지 않는다** —
            토스트 조상 체인이 `LI > OL > SECTION[aria-live=polite] > #root > BODY`인데 그 체인에 `aria-hidden`이
            한 곳도 없다(실측). **"Radix가 `#root`를 안 가려서"가 아니다** — modal 메뉴는 `hideOthers`를 실제로
            부르고 `header`·`main`에는 `aria-hidden="true"`가 붙는다(실측). 토스트가 사는 건 `aria-hidden`
            패키지가 **라이브 리전을 품은 가지를 건너뛰기** 때문이고, 그게 성립하는 건 sonner의
            `section[aria-live]`가 `#root` 안에 header·main과 형제로 상주하기 때문이다. **토스터를 `#root` 밖으로
            포털하거나 토스트가 없을 때 언마운트되게 바꾸면 이 보장이 조용히 깨진다**(이미 실행된 `hideOthers`는
            나중에 생긴 노드를 되살리지 않는다). */}
        <DropdownMenuItem
          disabled={logout.isPending}
          onSelect={(event) => {
            event.preventDefault();
            handleLogout();
          }}
        >
          <LogOut aria-hidden />
          로그아웃
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** 그룹을 눈으로만 만들지 않는다 — `DropdownMenuLabel`은 role 없는 div라 메뉴를 읽는 스크린리더가
 * 통째로 건너뛴다. `role="group"`(`DropdownMenuGroup`) + `aria-labelledby`로 묶어야 라벨이 그룹 이름으로
 * announce되고, 그래야 이 스토리가 만든 구조가 시각 사용자에게만 존재하지 않는다. */
function ProfileMenuGroup({ label, children }: { label: string; children: ReactNode }) {
  const labelId = useId();

  return (
    <DropdownMenuGroup aria-labelledby={labelId}>
      <DropdownMenuLabel id={labelId}>{label}</DropdownMenuLabel>
      {children}
    </DropdownMenuGroup>
  );
}
