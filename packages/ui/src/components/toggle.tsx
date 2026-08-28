import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Toggle as TogglePrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

/** 상류 shadcn은 on 상태를 `bg-muted`로 칠하지만, 이 시스템에서 그 값은 `background`와 명도가
 * 0.05밖에 차이 나지 않아(다크 0.210 vs 0.160) 선택이 보이지 않고 `hover:bg-muted`와도 구별되지
 * 않는다. DESIGN.md §2는 "활성 토글"을 `primary` 용처로 명시하므로 여기서 갈아끼운다 —
 * 호출부마다 같은 문자열을 붙이는 방식은 17곳 중 2곳만 맞고 나머지가 조용히 새는 걸 확인했다.
 * `shadcn add toggle`로 재생성하면 이 줄이 되돌아가니 주의할 것.
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
  "group/toggle inline-flex items-center justify-center gap-1 rounded-lg text-sm font-medium whitespace-nowrap motion-safe:transition-all outline-none hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 aria-pressed:bg-primary aria-pressed:text-primary-foreground data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:hover:bg-primary/80 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-transparent data-[state=on]:focus-visible:ring-ring aria-pressed:focus-visible:ring-ring",
        outline:
          "border border-input bg-transparent hover:bg-muted data-[state=on]:focus-visible:ring-ring aria-pressed:focus-visible:ring-ring",
        /** 세로로 쌓인 목록형 선택지(신고 사유 등). 행이 버튼보다 훨씬 넓어서 솔리드 채움을 쓰면
         * 같은 화면의 primary CTA와 같은 크기·같은 색 덩어리가 둘이 되어 무엇이 액션인지 흐려진다
         * (DESIGN.md 밝기 예산 규칙: primary 채움은 버튼 크기에 머문다). 색은 보더·텍스트·옅은
         * 틴트로만 얹어 CTA가 화면의 유일한 솔리드 채움으로 남게 한다. */
        list: "border border-input bg-transparent hover:bg-muted data-[state=on]:border-primary data-[state=on]:bg-primary/10 data-[state=on]:text-primary data-[state=on]:hover:bg-primary/15",
      },
      size: {
        default:
          "h-8 min-w-8 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        sm: "h-7 min-w-7 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 min-w-9 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
      },
    },
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
