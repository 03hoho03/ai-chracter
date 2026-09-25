import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Toggle as TogglePrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

/** 상류 shadcn은 on 상태를 `bg-muted`로 칠하지만, 이 시스템에서 그 값은 `background`와 명도가
 * 0.05밖에 차이 나지 않아(다크 0.210 vs 0.160) 선택이 보이지 않고 `hover:bg-muted`와도 구별되지
 * 않는다. DESIGN.md Colors 절은 "활성 토글"을 `primary` 용처로 명시하므로 여기서 갈아끼운다 —
 * 호출부마다 같은 문자열을 붙이는 방식은 17곳 중 2곳만 맞고 나머지가 조용히 새는 걸 확인했다.
 * `shadcn add toggle`로 재생성하면 이 줄이 되돌아가니 주의할 것.
 *
 * **Shape을 `rounded-full`(pill)로 바꾼 이유**. 레퍼런스
 * 둘 다 필터 칩과 액션 버튼을 반경으로 가른다 — 크랙은 필터 칩 pill / 액션 버튼 4px, 케이브덕은
 * 필터 칩 8~16px / 액션 버튼 4px. 이 프리미티브는 `Button`과 같은 `rounded-lg`(8px)를 써서 둘이
 * 형태로 안 갈렸다. **헤더의 캐릭터/스토리 토글도 함께 pill이 된다 — 의도된 것이다.** 그 토글은
 * 필터가 아니라 라우트 전환 탭이라 이질적으로 보일 수 있지만, 크랙·케이브덕처럼 버튼 형태 없이
 * 글자색만으로 활성/비활성을 가르는 텍스트 탭으로 바꾸겠다는 예고였다. **그 예고는 2026-09-14
 * 실행됐다** — 다만 프리미티브를 벗어나는 쪽이 아니라 아래
 * `variant="tab"`으로 프리미티브 **안에 남는** 쪽을 택했다. 벗어나면 roving tabindex·단일선택
 * 불변(재클릭 `""` emit 가드)·`aria-label`을 호출부가 손으로 다시 지어야 하고, DESIGN.md
 * §Toggles가 "호출부에 선택 상태 클래스를 직접 붙이지 말 것 — 17곳 중 2곳만 맞았다"를 금지한다.
 *
 * **비활성 글자를 `text-muted-foreground`로 낮춘 이유.** 레퍼런스는 비활성 → 활성 방향으로
 * 밝기가 오른다(크랙 탭 43%→96%, 케이브덕 탭 36%→100%, 크랙 필터 칩은 회색 텍스트→흰 텍스트+
 * 채움). 이 프리미티브는 비활성이 상속받은 `foreground`(0.930, 다크에서 사실상 천장)라 활성에서
 * 올릴 데가 없어 방향이 반대였다. 홈 화면에서 선택 안 된 장르 칩 10개가 전부 이 천장을 쓰는 것은
 * DESIGN.md Colors 절의 밝기 예산 규칙("밝은 면적은 예산이고 한 화면에서 지금 눌러야 할 단 하나에만
 * 쓴다")과 정면으로 어긋난다 — `text-muted-foreground`(0.680)로 낮춰 그 예산을 되찾는다. 대비
 * 실측(canvas 변환): 다크 on `background` **6.74:1** / on `card` **6.16:1**, 라이트 on
 * `background` **5.25:1** / on `card` **4.82:1** — 네 조합 전부 AA(4.5:1)를 넘는다.
 * `border-input`(WCAG 1.4.11 비텍스트 3:1을 지는 컨트롤 보더)은 값을 그대로 둔다 — 사다리에서
 * 3:1을 넘는 유일한 무채색 값이라(`border`는 다크 1.43:1 / 라이트 1.38:1로 이미 미달,
 * DESIGN.md Colors 절) 더 낮출 자리가 없다.
 *
 * **`variant="list"`는 위 두 변경을 둘 다 안 받는다** — 세로로 쌓인 목록형 선택지(신고 사유 등)라
 * 칩이 아니고, 칩 전제 위에 선 결정이 그대로 적용되지 않는다. 아래 variant 주석 참조.
 *
 * **`primary` 솔리드 채움을 쓰는 variant(`default`/`outline`)에서는 선택 시 포커스 링을 불투명하게
 * 쓴다**(`data-[state=on]:focus-visible:ring-ring`). `list`는 선택 상태가 `bg-primary/10` **틴트**라
 * 기본 레시피로도 3:1이 나오므로 제외한다 — 측정된 결함이 없는 곳까지 렌더를 바꾸지 않는다.
 * 기본 레시피의 `ring-ring/50`은 배경 위에서만 계산된 값이라, `primary` 솔리드 채움 위에서는
 * 포커스 표시가 통째로 무너진다 — `focus-visible:border-ring`이 보더를 채움과 **같은 핑크**로
 * 바꿔 rest에 있던 윤곽을 지우고(라이트 대비 1.0000 / 다크 1.0437), 남는 건 50% 링 하나인데 그게
 * 페이지 배경 대비 2.5757(다크) / 2.5511(라이트)로 WCAG 1.4.11의 3:1에 미달한다(두 리뷰어가
 * 독립 측정해 일치). ToggleGroup은 roving tabindex라 **Tab이 닿는 칩은 언제나 선택된 칩 하나**여서
 * 이건 엣지가 아니라 이 프리미티브의 기본 포커스 상태다. 불투명 링은 7.18(다크) / 6.70(라이트). */
const toggleVariants = cva(
  "group/toggle inline-flex items-center justify-center gap-1 rounded-full text-sm font-medium text-muted-foreground whitespace-nowrap motion-safe:transition-all outline-none hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 aria-pressed:bg-primary aria-pressed:text-primary-foreground data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:hover:bg-primary/80 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-transparent data-[state=on]:focus-visible:ring-ring aria-pressed:focus-visible:ring-ring",
        outline:
          "border border-input bg-transparent hover:bg-muted data-[state=on]:focus-visible:ring-ring aria-pressed:focus-visible:ring-ring",
        /** 세로로 쌓인 목록형 선택지(신고 사유 등). 행이 버튼보다 훨씬 넓어서 솔리드 채움을 쓰면
         * 같은 화면의 primary CTA와 같은 크기·같은 색 덩어리가 둘이 되어 무엇이 액션인지 흐려진다
         * (DESIGN.md 밝기 예산 규칙: "밝은 면적은 예산이고, 한 화면에서 지금 눌러야 할 단 하나에만
         * 쓴다" — 화면당 `primary` 솔리드 채움은 하나). 색은 보더·텍스트·옅은 틴트로만 얹어 CTA가
         * 화면의 유일한 솔리드 채움으로 남게 한다.
         *
         * **위 두 변경(pill · 비활성 글자 다운) 양쪽에서 제외한다** — `rounded-lg`와
         * `text-foreground`로 되돌린다. pill을 준 이유는 *칩*과 액션 버튼을 형태로 가르는
         * 것인데, 이 variant는 애초에 칩이 아니라 한 줄을 가득 채우는 행이다(아래 감사 테스트가
         * 그 경계다). 실제로 신고 모달의 행은 호출부가 `h-11`로 올려 **352×44px**이라, pill을 주면
         * 반경이 **22px**이 되어 바로 아래 **36px·8px**인 CTA보다 선택지 쪽이 더 버튼처럼 읽혀
         * pill의 의도가 뒤집힌다(실측: 행 352×44 / CTA 높이 36 · 반경 8px). 글자 다운도
         * 같은 이유로 안 받는다 — 필터 칩은 이미 뭘 뜻하는지 아는 항목을 반복해서 훑는 자리지만,
         * 여기는 처음 보는 여러 문장을 전부 읽고 하나를 고르는 자리다. 렌더해서 눈으로 봤을 때
         * 6.74:1도 또렷이 읽혔지만 그 확인이 "읽는 부담이 없다"를 보장하진 않는다 — 대비 수치와
         * 읽기 부담은 별개 축이라 눈으로 통과했다는 이유로 다운을 씌우지 않는다. */
        list: "rounded-lg border border-input bg-transparent text-foreground hover:bg-muted data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15",
        /** 라우트 전환 탭이 하나뿐인 자리(헤더 캐릭터/스토리).
         * 필터 칩에는 쓰지 않는다 — 채움·보더 없이 글자색과 `after:` 밑줄로만 활성을 가른다.
         *
         * `relative` — 베이스에 없다. 없으면 `after:absolute` 밑줄이 포지셔닝 컨텍스트를 못 찾고
         * 상위(헤더)로 흘러 엉뚱한 곳에 찍힌다.
         *
         * `rounded-md` — 채움이 없어도 `focus-visible:ring-*`은 반경을 따라간다. 안 주면 포커스
         * 링이 알약 모양으로 남는다(`tabs.tsx` 트리거와 같은 값).
         *
         * `border border-transparent` — 장식이 아니라 WCAG 1.4.11을 지는 하중 부재다.
         * `focus-visible:border-ring`(베이스에 있음)이 이걸 불투명 핑크로 바꿔 포커스를 드러낸다.
         * 50% 링만으로는 배경 대비 2.5757(다크)로 3:1 미달이다(DESIGN.md §Toggles 실측) — 지우지
         * 말 것. `tab`은 활성 솔리드 채움이 없어 `default`/`outline`/`list`가 쓰는 불투명 포커스
         * 링 오버라이드(`data-[state=on]:focus-visible:ring-ring`)가 필요 없다 — 보더 하나로 이미
         * 3:1을 지므로 이건 실측이 아니라 구조적 결론이다.
         *
         * **활성 채움 제거는 베이스와 같은 modifier chain으로 재선언해야 twMerge가 지운다**
         * (`packages/ui/CLAUDE.md`, 2026-09-14 스크립트로 재현) — chain이 다르면
         * `data-[state=on]:bg-primary`(특이도 0,2,0)가 평평한 `bg-transparent`(0,1,0)를 이겨 활성
         * 탭이 핑크로 남는다. `data-[state=on]:hover:bg-primary/80`은 3중 chain이라
         * `data-[state=on]:hover:bg-transparent`로 **별도** 선언한다 — 안 하면 활성 탭 hover에서만
         * 반투명 핑크가 스친다. `aria-pressed:*`도 함께 덮는 이유는 `ToggleGroup`이 `data-state`,
         * standalone `Toggle`이 `aria-pressed`를 쓰기 때문이다(`type="single"`에서는 Radix가
         * `aria-pressed`를 지워 죽은 경로지만, DESIGN.md §Toggles가 "호출부에 선택 상태 클래스를
         * 직접 붙이지 말 것 — 17곳 중 2곳만 맞았다"를 근거로 규칙을 프리미티브에 두라고 못박아
         * 그대로 둔다). `hover:bg-transparent`가 없으면 비활성 탭 hover에 회색 알약이 남는다 —
         * `hover:text-foreground`는 베이스에 이미 있어 그대로 재사용한다.
         *
         * `after:` 밑줄 — 이 앱의 유일한 밑줄 어휘(`tabs.tsx` line variant)를 가져오되
         * **`bottom-[-5px]`는 베끼지 않는다.** 그 값은 `TabsList`의 `h-9`+`p-[3px]`와 트리거의
         * `h-[calc(100%-1px)]`가 만드는 약 3.5px 트로프를 상쇄하는 값이라, 그 패딩이 없는
         * `ToggleGroup`에 그대로 쓰면 밑줄이 헤더 `border-b`와 3px 거리에서 이중선으로 읽힌다.
         * **`tabs.tsx`의 `group-data-horizontal/tabs:` · `group-data-[variant=line]/tabs-list:`
         * 도 베끼지 않는다** — 그 셀렉터는 `tabs`/`tabs-list`라는 group 이름에 의존하는데
         * `ToggleGroup`이 여는 group 이름은 `toggle-group` 하나뿐이라 조용히 죽는다.
         * `ToggleGroupItem`은 cva `variant`를 직접 받으므로 2단 group 트릭 자체가 불필요하다 —
         * `tab`은 수평 전용(세로 호출부 0곳)이라 group 접두사 없이 직접 선언한다.
         *
         * 좌우 패딩은 아래 `compoundVariants`가 size `default`의 `px-4`를 `px-2`로 내린다 —
         * **텍스트 탭은 채움이 없어 알약 패딩이 필요 없다.** `px-4`는 배경이 pill로 보이게 여백을
         * 벌리던 값인데 `tab`은 배경 자체가 없으므로 패딩은 모양이 아니라 히트 영역만 정한다.
         * `h-9`(36px)는 그대로 유지하므로 WCAG 2.5.8(24×24 타깃)은 `px-2`로 줄여도 만족한다.
         * (부수 효과로 항목당 16px씩 폭이 줄지만, 그게 이 값을 고른 이유는 아니다.)
         *
         * **여기 variant 문자열에 직접 `px-2`를 넣으면 안 먹는다.** cva는
         * `base + variant + size + className` 순으로 이어붙이는데 `size`가 `variant`보다 뒤에 와서,
         * 같은 그룹(`px-*`)에서 twMerge는 더 뒤에 오는 클래스를 남긴다 — variant의 `px-2`보다 size의
         * `px-4`가 뒤에 있어 `px-4`가 이겨 버린다(2026-09-14 직접 재현, 프리미티브 충돌 전수 조사엔 없던 함정).
         * `compoundVariants`는 `size` 다음에 이어붙으므로 그 자리에서 주면 twMerge가 마지막
         * 값으로 인정한다. */
        tab: "relative rounded-md border border-transparent hover:bg-transparent data-[state=on]:bg-transparent data-[state=on]:text-foreground data-[state=on]:hover:bg-transparent aria-pressed:bg-transparent aria-pressed:text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-foreground after:opacity-0 data-[state=on]:after:opacity-100 motion-safe:after:transition-opacity",
      },
      /** `button.tsx`의 size 표와 같은 값 — 장르 필터·헤더
       * 토글·테마 선택·빌더 시작설정이 전부 이 하나에서 나온다. `text-[0.8rem]`(12.8px) 하드코딩을
       * `sm`에서 제거해 `text-xs`(지금 14px)를 쓰고, `has-data-[icon=*]:p{r,l}-*` 보정값은
       * 각 사이즈가 원래 갖던 델타(default/lg -0.5unit, sm -1unit)를 새 베이스 패딩에 그대로 옮겼다.
       * `sm`이 32px 티어로 올라가므로 `rounded-[min(var(--radius-md),12px)]` 캡도 걷어 기본
       * 반경을 상속하게 한다 — `button.tsx`의 `sm`/`icon-sm`과 같은 이유다(같은
       * 32px 안에서 모서리가 갈리지 않게). 기본 반경은 이 size 표를 맞출 때엔 `rounded-lg`(8px)
       * 였고 이후 `rounded-full`로 바뀌었다 — `sm`이 그 값을 그대로 물려받는다는 점은 안 변했다. */
      size: {
        default:
          "h-9 min-w-9 px-4 has-data-[icon=inline-end]:pr-3.5 has-data-[icon=inline-start]:pl-3.5",
        sm: "h-8 min-w-8 px-3 text-xs has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-10 min-w-10 px-4 has-data-[icon=inline-end]:pr-3.5 has-data-[icon=inline-start]:pl-3.5",
      },
    },
    /** `tab` variant의 `px-2`는 여기서만 이긴다 — 위 `tab` 주석의 cva 이어붙임 순서(base+variant+
     * size) 설명 참조. `size: "default"`로 좁힌 이유는 `tab`+`sm`/`lg` 조합 호출부가 아직 0곳이라
     * 그 조합까지 미리 처방하지 않는다(호출되면 그때 넓힌다). */
    compoundVariants: [{ variant: "tab", size: "default", class: "px-2" }],
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Toggle({
  className,
  variant = "default",
  size = "default",
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> &
  VariantProps<typeof toggleVariants>) {
  return (
    <TogglePrimitive.Root
      data-slot="toggle"
      className={cn(toggleVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Toggle, toggleVariants }
