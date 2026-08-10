import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Toggle as TogglePrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

/** 상류 shadcn은 on 상태를 `bg-muted`로 칠하지만, 이 시스템에서 그 값은 `background`와 명도가
 * 0.05밖에 차이 나지 않아(다크 0.210 vs 0.160) 선택이 보이지 않고 `hover:bg-muted`와도 구별되지
 * 않는다. DESIGN.md §2는 "활성 토글"을 `primary` 용처로 명시하므로 여기서 갈아끼운다 —
 * 호출부마다 같은 문자열을 붙이는 방식은 17곳 중 2곳만 맞고 나머지가 조용히 새는 걸 확인했다.
 * `shadcn add toggle`로 재생성하면 이 줄이 되돌아가니 주의할 것. */
const toggleVariants = cva(
  "group/toggle inline-flex items-center justify-center gap-1 rounded-lg text-sm font-medium whitespace-nowrap transition-all outline-none hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 aria-pressed:bg-primary aria-pressed:text-primary-foreground data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:hover:bg-primary/80 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-transparent",
        outline: "border border-input bg-transparent hover:bg-muted",
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
