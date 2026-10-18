import * as React from "react"
import { Popover as PopoverPrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

function Popover({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

/** 누르면 열리는 떠 있는 패널. 표면은 메뉴·툴팁과 같은 Floating panel 레시피(DESIGN.md Elevation 절 — `popover` +
 * `shadow-md` + `ring-1 ring-foreground/10`)이고, 그림자는 열린 동안에만 있다.
 *
 * 포털로 띄운다 — 트리거가 가로 스크롤 줄(`overflow-x-auto`) 안에 있어도 패널이 잘리지 않는다. Radix 가 Esc·바깥 누름으로
 * 닫고 포커스를 트리거로 돌려준다. 등장·퇴장은 시간까지 `motion-safe:` 로 가드한다(팝오버 100ms, DESIGN.md Motion 절).
 * 이름이 필요한 패널(제목 없는 `role="dialog"`)은 호출부가 `aria-label` 을 준다. */
function PopoverContent({
  className,
  align = "start",
  sideOffset = 6,
  collisionPadding = 8,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          "z-50 w-64 origin-(--radix-popover-content-transform-origin) rounded-lg bg-popover p-3 text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden motion-safe:duration-100 motion-safe:data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}

export { Popover, PopoverContent, PopoverTrigger }
