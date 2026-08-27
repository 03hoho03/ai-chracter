import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap motion-safe:transition-all outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        /** `focus-visible:ring-ring`(불투명)은 base의 `ring-ring/50`을 덮는다 — **`primary` 솔리드
         * 채움 위에서는 기본 레시피가 통째로 무너지기 때문이다.** `focus-visible:border-ring`이
         * `--ring == --primary`라 보더를 채움과 **같은 색**(1.0000:1)으로 칠해 rest의 1px 윤곽을
         * 지우고, 남는 50% 링은 페이지 배경 대비 2.5757(다크)/2.5511(라이트)로 WCAG 1.4.11의 3:1에
         * 미달한다(두 스토리에서 독립 측정해 일치). 불투명 링은 7.1768/6.7011. `toggle.tsx`가 선택
         * 상태에 대해 US-009에서 같은 처방을 이미 했고, 이건 그 나머지 절반이다 — 두 프리미티브가
         * 같은 채움을 쓰는데 포커스 표시만 갈리면 관습이 나뉜다. 다른 variant는 채움이 무채색이거나
         * `/10` 틴트라 측정된 결함이 없으므로 base를 건드리지 않고 여기까지만 좁힌다. */
        default: "bg-primary text-primary-foreground hover:bg-primary/80 focus-visible:ring-ring",
        outline:
          "border-input bg-background hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)] aria-expanded:bg-secondary aria-expanded:text-secondary-foreground",
        ghost:
          "hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground",
        /** `destructive`는 하우스 레시피의 **알파만** 되돌린다(US-004) — base의 `border-ring`·`ring-ring/50`을
         * destructive hue로 갈아끼우되 보더는 불투명, 링은 50%다. 고치기 전에는 보더 40% · 링 20%라
         * 포커스가 **어느 쪽으로도 보이지 않았다**(링 대 페이지 배경 1.2371 다크 / 1.3694 라이트, 링 대
         * 자기 채움 1.1312 / 1.1728). 불투명 보더는 자기 채움(`bg-destructive/10`) 대비 **4.8431 / 4.5795**,
         * 페이지 배경 대비 **5.2933 / 5.3328**로 WCAG 1.4.11(3:1)을 넘는다 — 3:1을 지는 건 링이 아니라
         * 이 1px 보더이고, 그건 `로그아웃`·인풋·제출 버튼이 이미 쓰는 것과 **같은 구조**다.
         * `/10` 틴트 채움이라 `default`처럼 불투명 링까지 갈 필요가 없다(`toggle.tsx`의 `list`가 같은 이유로
         * 기본 레시피를 그대로 쓴다) — 불투명 링이 필요한 건 보더가 채움에 먹히는 **솔리드 채움**뿐이다.
         * 참고로 50% 링 자체는 페이지 배경 대비 2.1017 / 2.2862로, 하우스 레시피의 링과 같은 등급이다. */
        destructive:
          "bg-destructive/10 text-destructive-text hover:bg-destructive/20 focus-visible:border-destructive focus-visible:ring-destructive/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-8 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        icon: "size-8",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-7 rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
