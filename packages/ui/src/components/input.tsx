import * as React from "react"

import { cn } from "@ai-character-chat/ui/lib/utils"

/** `h-9`·`px-3` — 버튼 `default`(36px)와 같은 높이 티어로 맞춘다(design-system-goal-prompt.md D-4).
 * `py-1`은 걷어냈다 — `Button`/`Toggle`이 세로 패딩 없이 `h-*` + `items-center`만으로 중앙정렬하는
 * 계보를 `select.tsx`가 이미 택했고(design-system-progress.md P-2a), 이 프리미티브만 패딩으로 높이를
 * 만들면 같은 높이 티어에서 시각적으로 안 같아진다. `h-9`가 명시돼 있어 `py-1`은 잉여다. */

/** `text-base`(16px) 고정 — `md:text-sm`을 지운 것도 이 이유다. 16px 미만 입력에 포커스하면
 * iOS Safari가 자동으로 확대한다(표준 관용구). `--text-sm`이 16px가 된 뒤로는 그 오버라이드가
 * 아무 효과 없는 죽은 코드였다(design-system-goal-prompt.md D-5/D-8). */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-lg border border-input bg-transparent px-3 text-base motion-safe:transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
        className
      )}
      {...props}
    />
  )
}

export { Input }
