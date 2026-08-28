import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { Link, useNavigate } from "@tanstack/react-router";
import { useAtom } from "jotai";
import { Moon, Sun } from "lucide-react";
import { toast } from "sonner";

import { ChangePasswordForm } from "@/features/change-password";
import { useLogoutMutation } from "@/features/logout";
import { WithdrawAccountDialog } from "@/features/withdraw-account";
import type { Theme } from "@/shared/model/theme";
import { themeAtom } from "@/shared/model/theme";

/** prd-creator-entry-and-my-works.md US-013 — 설정 전용 페이지(테마 · 비밀번호 변경 · 계정).
 *
 * `작성 중인 초안` 섹션은 `/my`로 옮겼다(FR-26). 초안이 두 화면에 중복으로 살면 US-003의 삭제·US-004의
 * 편집 취소가 한쪽에만 있어 두 목록이 서로 다른 진실을 말하게 된다.
 *
 * **여기는 어제까지 초안이 있던 주소라 `/my` 링크를 본문에 둔다**(AC5는 이 판단을 구현에 위임했다).
 * 한때 이 자리에 "링크가 아니라 문장을 두는 이유는 크롬을 늘리지 않기 위해서"라고 적어 뒀는데 **그건 범주
 * 오류였다** — 루트 CLAUDE.md가 금지한 건 하단 탭바·사이드 레일·푸터이지 `<main>` 안 본문 링크가 아니다.
 * 실제 비용은 탭 스톱 하나(6→7)뿐인데, 그걸 아끼는 대가로 초안을 찾아 온 창작자에게 읽기→기억→아이콘 메뉴
 * 탐색 3단계를 시키고 있었다(고치기 전 `<main>` 안 `<a>` 실측 **0개**).
 *
 * 문장에서 `프로필 메뉴`라는 말도 뺐다 — **그 이름은 화면 어디에도 보이지 않는다**(헤더 트리거는 아이콘
 * 전용이고 접근가능 이름은 `~님 메뉴`다). 목적지로 가는 경로를 외우게 하는 대신 목적지를 직접 누르게 한다.
 *
 * 중복 진입점 걱정은 실측으로 기각됐다 — 다만 **이유가 두 겹이고, 한 겹만 적으면 틀린다**. 메뉴가 닫혀
 * 있으면 Radix가 `DropdownMenuContent`를 DOM에서 통째로 언마운트하므로 `내 작품` 링크는 1개다. 그런데
 * 메뉴가 **열려 있으면 DOM에는 실제로 2개가 존재한다**(실측). 그때 목록을 1개로 지키는 건 언마운트가
 * 아니라 Radix가 `main`·`header`에 거는 `aria-hidden="true"`다 — 접근성 트리 기준으로 세면 열림·닫힘
 * 양쪽 모두 **정확히 1개**다(`a[href]` 중 `closest('[aria-hidden="true"]')`가 없는 것만 카운트한 실측).
 * 그래서 이 불변식은 **토스터를 포털로 옮기듯 `main` 바깥으로 무언가를 꺼내는 순간 조용히 깨진다.**
 */
export function MyPagePage() {
  return (
    // 컬럼은 `max-w-2xl`(672px)이 아니라 `max-w-md`(448px)다. DESIGN.md §5는 폼 화면을 `max-w-2xl`로
    // 적어 뒀지만 그 폭을 정당화하던 건 초안 그리드였고, US-013이 그걸 `/my`로 옮기면서 근거가 사라졌다.
    //
    // **폭의 근거는 컨트롤이 아니라 텍스트다.** 한때 이 자리에 "가장 넓은 컨트롤보다 288px 넓다",
    // "448px이면 인풋이 콘텐츠 박스를 채워 표류가 0이 된다"고 적어 뒀는데 **둘 다 두 폭을 구별하지
    // 못하는 항진명제였다** — `Input`이 `w-full`이라 `max-w-md`에서 400px, `max-w-2xl`에서 624px로
    // **어느 폭에서든 콘텐츠 박스를 정확히 채운다**(A/B 실측). 실제로 갈리는 건 텍스트 쪽인데, 이유는
    // 잉크 폭이 고정이어서가 아니라 **컬럼만큼 빨리 늘지 않아서**다: 산문은 늘어난 폭을 줄바꿈으로
    // 흡수하고 마지막 줄이 오른쪽에 빈자리를 남기므로, 콘텐츠 박스를 400→624px(+224)로 늘려도 잉크는
    // 391.13→450.11px(+59)까지만 늘어난다. 남는 폭이 전부 오른쪽에 쌓여 잉크 중심이 왼쪽으로 밀린다 —
    // 뷰포트 중심 대비 `max-w-md` **−4.44px**, `max-w-2xl` **−86.95px**(1280px A/B 실측).
    // 카드도 보더도 사이드 레일도 없어 컬럼 경계가 화면에 안 그려지므로 이 어긋남은 여백이 아니라
    // **정렬 오차**로 읽힌다. 박스 자체는 두 폭 모두 정확히 중앙이지만(drift 0) 그 박스를 그리는 유일한
    // 선인 인풋 보더가 배경 대비 1.4312 다크 / 1.3845 라이트라 눈에 남는 건 텍스트뿐이다.
    //
    // `gap-10`(40px)은 유지한다. 섹션 내부가 `gap-4`(16px)라 2.5배고, 32px로 내리면 2.0배다(저장소는 이미
    // 1.5배를 Gestalt 임계 미달로 판정해 뒀다 — `apps/web/CLAUDE.md` 필터 축). 뷰포트를 못 채우는 것은
    // 간격을 좁힐 근거가 아니다 — 좁히면 그 여백만 늘어난다. 채우려면 카드·패널이 필요한데 DESIGN.md가
    // 금지하고, 설정 화면은 원래 짧다.
    <main className="mx-auto flex max-w-md flex-col gap-10 px-6 py-10">
      {/* h1과 설명을 6px(`gap-1.5`)로 묶어 설명이 제목의 일부로 읽히게 한다 — 바깥 40px과 6.67배 차이다.
          **바깥 간격은 여기서 위계를 지지 않는다**: 헤더 블록→첫 섹션도 섹션↔섹션도 실측 40.0px으로 같다.
          한때 이 주석은 묶기가 그 비대칭을 만들었다고 적었는데 **거짓이었다** — 묶기가 바꾼 건 설명의
          소속이지 헤더와 본문의 분리가 아니다. 그래도 균일 gap을 두는 이유는 컨테이너 하나에 `gap-*` 하나가
          이 앱의 페이지 관용구이고(DESIGN.md §5, 형제 페이지 `StudioImagesPage`도 같은 h1+설명 블록을 균일
          gap에 둔다), 제목은 위치가 아니라 타이포로 갈리기 때문이다(h1 24/700 vs h2 20/600 — 계산된 속성
          580개 중 9개가 다르고 그중 크기·굵기·자간 3개가 authored. 고치기 전에는 이 diff가 0이었다).
          이 문단은 접히므로 `break-keep`이 필요하다 — 320px에서 2줄이 된다(한때 여기 "이 `<main>`에서
          **유일하게** 줄바꿈이 일어나는 산문"이라고 적어 뒀는데, 계정 섹션 경고 문장이 생기면서 거짓이
          됐다. 그쪽은 320~1280 **전 구간**에서 접힌다). */}
      <div className="flex flex-col gap-1.5">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">설정</h1>
        <p className="text-sm break-keep text-muted-foreground">
          화면과 계정을 관리해요. 만든 작품과 초안은{" "}
          {/* 문장 속 링크는 `font-medium text-primary hover:underline`이 저장소 관용구다(`LoginForm`·
              `SignUpPage` 선례). 여기에 둘을 더했다.
              · `whitespace-nowrap` — `break-keep`은 어절 경계를 허용하므로 `내 / 작품`으로 갈린다(320px에서
                실측 2줄). 목적지 이름이 두 줄에 걸치면 읽기도 누르기도 나빠진다. 40px짜리 어구라 272px
                컬럼에서도 넘칠 위험이 없다.
              · `focus-visible:underline` — 전역 base(`globals.css`의 `outline-ring/50`)가 주는 건 1px UA
                아웃라인 하나뿐이고 실측 **2.5757 다크 / 2.5511 라이트**로 WCAG 1.4.11(3:1)에 미달한다. 카드
                링크용 3px 링 레시피는 문장 안에서 라인박스를 깨므로 쓸 수 없다 — 대신 밑줄을 더한다.
                `text-primary`라 밑줄 대비가 배경 대비 **7.1768 / 6.7011**이고, 아웃라인은 그대로 남긴다
                (`StoryDetailBody` 선례. 단 거기처럼 `outline-none`으로 지우지는 않는다). */}
          <Link
            to="/my"
            className="font-medium whitespace-nowrap text-primary hover:underline focus-visible:underline"
          >
            내 작품
          </Link>
          에 있어요.
        </p>
      </div>

      <ThemeSection />

      <section className="flex flex-col gap-4">
        <SectionHeading>비밀번호 변경</SectionHeading>
        <ChangePasswordForm />
      </section>

      <AccountSection />
    </main>
  );
}

/** 섹션 제목은 Display(24/700)가 아니라 Title(20/600)이다 — **정책과 census는 `DESIGN.md` §3 Hierarchy에
 * 있고 여기 복사하지 않는다**(두 곳에 적으면 다음 개정 때 갈린다).
 *
 * 코드에 남길 사실 하나: 고치기 전 h1과 세 h2는 **계산된 속성 580개가 전부 일치**했다(실측 diff 0건).
 * 이 화면에서 제목과 섹션을 가르는 축이 태그 이름밖에 없었다는 뜻이다. */
function SectionHeading({ children }: { children: string }) {
  return <h2 className="text-xl font-semibold tracking-tight text-foreground">{children}</h2>;
}

function isTheme(value: string): value is Theme {
  return value === "dark" || value === "light";
}

function ThemeSection() {
  const [theme, setTheme] = useAtom(themeAtom);

  const handleValueChange = (value: string) => {
    // Radix ToggleGroup(type="single")은 이미 선택된 항목을 다시 누르면 빈 문자열을 emit한다 — 그 경우 무시해
    // 항상 정확히 하나만 선택된 상태를 유지한다.
    if (!isTheme(value)) return;
    setTheme(value);
  };

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading>테마</SectionHeading>
      <ToggleGroup
        type="single"
        variant="outline"
        value={theme}
        onValueChange={handleValueChange}
        aria-label="테마 선택"
      >
        <ToggleGroupItem value="dark">
          <Moon aria-hidden />
          다크
        </ToggleGroupItem>
        <ToggleGroupItem value="light">
          <Sun aria-hidden />
          라이트
        </ToggleGroupItem>
      </ToggleGroup>
    </section>
  );
}

function AccountSection() {
  const navigate = useNavigate();
  const logoutMutation = useLogoutMutation();

  const handleLogout = () => {
    logoutMutation.mutate(undefined, {
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
    // 되돌릴 수 있는 액션과 없는 액션을 **질량**으로 가른다. 커밋된 이전 상태는 두 버튼을
    // `flex flex-wrap gap-2`로 **나란히** 둔 것이었는데(가로 8px), 한글 4자·같은 패딩이라
    // **70.41×32px로 폭까지 완전히 같아**(실측) 되돌릴 수 있는 것과 없는 것이 "둘 중 하나 고르기"로
    // 읽혔다. `flex-wrap`은 덤으로 죽은 코드였다 — 390px에서도 70.41×2+8이 272px 안에 들어가 한 번도
    // 발화하지 않는다.
    //
    // **간격은 이 문제를 풀 수 있는 축이 아니다.** 비율 논증에는 같은 시야 안의 참조 간격이 필요한데
    // 버튼이 둘뿐이라 그룹 내부 간격이 아예 없다. 형태도 못 쓴다 — `destructive` 틴트는 채움 대비가
    // 다크 1.0936 / 라이트 1.1676이라 알약 모양을 못 만들고 글자 색만 바꾼다(솔리드 레드는 DESIGN.md가
    // 금지한다). **여기 적혀 있던 "그 색조차 hover에서 4.2817 / 3.8943으로 AA 아래"는 US-003에서
    // 무효가 됐다** — `--destructive-text`가 갈라지면서 hover가 5.1877 / 5.0692다. 형태를 못 쓰는 근거는
    // 채움 대비 쪽이고(그건 그대로다) 텍스트 대비 쪽이 아니었다.
    //
    // 남는 축이 질량이라 **탈퇴 버튼에 대가를 먼저 말하는 문장을 붙였다.** 맨몸 32px 버튼과 78px짜리
    // 산문+버튼 블록은 질량이 달라 대등한 선택지로 읽히지 않는다. **기전을 정확히 적어 둔다** — 이걸
    // "사다리가 섰다"로 적으면 다음 개정에서 오독된다: 섹션 최상위 사다리는 **여전히** h2↔로그아웃 16px :
    // 로그아웃↔탈퇴블록 16px = **1.0000배**이고, 2.6667배 티어(16:6)는 탈퇴 블록 *내부*에만 생겼다.
    // 두 액션을 실제로 가른 건 질량과 **거리**다 — 버튼 사이 실거리가 16 → **62px**로 벌어져 비가역
    // 액션의 오조작 여유도 함께 늘었다(전부 1280px 실측).
    //
    // **문장은 짧게 두고 완전한 설명은 모달이 진다.** 이 문장의 일은 "비싸고 되돌릴 수 없다"를 누르기
    // 전에 알리는 것뿐이다. 초안 보존·접근 불가까지 담으면 확인 모달이 이 문장의 재진술이 되고, 반대로
    // 모달을 델타로 줄이면 페이지 문장을 읽지 않고 온 사용자에게 **마지막 관문이 불완전해진다**. 둘 다
    // 2차 리뷰에서 제안됐지만 서로 반대 방향이라, 역할을 갈라 양쪽을 각각 완결시키는 쪽을 골랐다.
    <section className="flex flex-col items-start gap-4">
      <SectionHeading>계정</SectionHeading>
      <Button variant="outline" disabled={logoutMutation.isPending} onClick={handleLogout}>
        {logoutMutation.isPending ? "로그아웃 중..." : "로그아웃"}
      </Button>
      <div className="flex flex-col items-start gap-1.5">
        {/* `되돌릴 수 없어요.`를 `whitespace-nowrap`으로 묶는다 — `break-keep`만으로는 448px 컬럼(≥768px,
            즉 데스크톱 기본)에서 `…비공개로 전환돼요. 되돌릴` / `수 없어요.`로 접혀 **심각도를 지는 절이
            갈리고 55.47px 위도우**가 남는다(실측). 어절 경계라 `break-keep` 위반은 아니지만 저장소가 이미
            기록한 "줄바꿈 결함은 넓은 쪽에만 있을 수 있다"의 재발이다 — 320/390에서는 문장 경계로 깨끗이
            접힌다. 묶어도 272px 컬럼(320px)에서 넘칠 길이가 아니다. */}
        <p className="text-sm break-keep text-muted-foreground">
          탈퇴하면 대화기록이 삭제되고 발행한 작품은 비공개로 전환돼요.{" "}
          <span className="whitespace-nowrap">되돌릴 수 없어요.</span>
        </p>
        <WithdrawAccountDialog />
      </div>
    </section>
  );
}
