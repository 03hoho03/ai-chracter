import * as React from "react"
import { Tooltip as TooltipPrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"

function TooltipProvider({
  delayDuration = 300,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot="tooltip-provider"
      delayDuration={delayDuration}
      {...props}
    />
  )
}

function Tooltip({
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />
}

function TooltipTrigger({
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

/** **표면은 상류의 반전 말풍선(`bg-foreground text-background`)이 아니라 떠 있는 팝오버와 같은 레시피다**(DESIGN.md
 * Elevation 절 Floating panel — `popover` + `shadow-md` + `ring-1 ring-foreground/10`). 다크에서 반전 말풍선은 0.930
 * 면이 포인터를 올리는 순간 켜지는 것이라 예고 없는 대비 점프다. 화살표도 그 레시피에 없어 두지 않는다.
 *
 * Radix 는 열린 동안 트리거에 `aria-describedby` 로 툴팁 글자를 잇는다. 툴팁 글자가 트리거의 접근 이름과 같으면(아이콘만
 * 보이는 버튼의 이름표) 스크린리더가 같은 말을 두 번 읽으므로, 그런 호출부는 트리거에 `aria-describedby={undefined}`
 * 를 넘겨 연결을 끊는다 — 트리거가 넘겨받은 props 를 Radix 기본값 뒤에 펼치므로 그 값이 이긴다.
 *
 * Radix 툴팁의 열린 상태는 `open` 이 아니라 `delayed-open`/`instant-open` 이라 `data-open:` 축약 variant 가 맞지 않는다.
 * 등장은 지연 뒤 열릴 때만 움직이고(이웃 칸으로 옮겨 바로 열리는 `instant-open` 은 즉시), 시간까지 `motion-safe:` 로
 * 가드한다(팝오버 100ms, DESIGN.md Motion 절). */
function TooltipContent({
  className,
  sideOffset = 8,
  collisionPadding = 8,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          "z-50 w-fit max-w-xs origin-(--radix-tooltip-content-transform-origin) rounded-lg bg-popover px-2.5 py-1.5 text-xs text-foreground shadow-md ring-1 ring-foreground/10 motion-safe:duration-100 motion-safe:data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        {...props}
      >
        {children}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  )
}

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }
