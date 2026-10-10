import * as React from "react"
import { Dialog as SheetPrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"
import {
  shouldSuppressClickAfterSwipe,
  toReleaseVelocity,
  toSheetSettleDurationMs,
  toSheetSwipeOffset,
  toSheetSwipeRelease,
  toSheetSwipeStart,
  SHEET_SWIPE_VELOCITY_WINDOW_MS,
  type PointerSample,
  type SheetSwipeStart,
} from "@ai-character-chat/ui/lib/sheet-swipe"
import { Button } from "@ai-character-chat/ui/components/button"
import { XIcon } from "lucide-react"

function Sheet({ ...props }: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />
}

function SheetTrigger({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Trigger>) {
  return <SheetPrimitive.Trigger data-slot="sheet-trigger" {...props} />
}

function SheetClose({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Close>) {
  return <SheetPrimitive.Close data-slot="sheet-close" {...props} />
}

function SheetPortal({
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Portal>) {
  return <SheetPrimitive.Portal data-slot="sheet-portal" {...props} />
}

function SheetOverlay({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      data-slot="sheet-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/10 motion-safe:duration-100 supports-backdrop-filter:backdrop-blur-xs motion-safe:data-open:animate-in data-open:fade-in-0 motion-safe:data-closed:animate-out data-closed:fade-out-0",
        className
      )}
      {...props}
    />
  )
}

function SheetContent({
  className,
  children,
  side = "right",
  showCloseButton = true,
  ref,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & {
  side?: "top" | "right" | "bottom" | "left"
  showCloseButton?: boolean
}) {
  const swipeCloseRef = React.useRef<HTMLButtonElement>(null)
  const isSwipeable = side === "left"
  const contentRef = React.useCallback(
    (node: HTMLDivElement | null) => {
      setRef(ref, node)
      const detachSwipe =
        node && isSwipeable
          ? attachSwipeToClose(node, () => swipeCloseRef.current?.click())
          : undefined
      return () => {
        detachSwipe?.()
        setRef(ref, null)
      }
    },
    [ref, isSwipeable]
  )

  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        ref={contentRef}
        data-slot="sheet-content"
        data-side={side}
        className={cn(
          "fixed z-50 flex flex-col gap-4 bg-popover bg-clip-padding text-sm text-popover-foreground shadow-lg motion-safe:transition motion-safe:duration-200 ease-in-out data-[side=bottom]:inset-x-0 data-[side=bottom]:bottom-0 data-[side=bottom]:h-auto data-[side=bottom]:border-t data-[side=left]:inset-y-0 data-[side=left]:left-0 data-[side=left]:h-full data-[side=left]:w-3/4 data-[side=left]:touch-pan-y data-[side=left]:touch-pinch-zoom data-[side=left]:border-r data-[side=right]:inset-y-0 data-[side=right]:right-0 data-[side=right]:h-full data-[side=right]:w-3/4 data-[side=right]:border-l data-[side=top]:inset-x-0 data-[side=top]:top-0 data-[side=top]:h-auto data-[side=top]:border-b data-[side=left]:sm:max-w-sm data-[side=right]:sm:max-w-sm motion-safe:data-open:animate-in data-open:fade-in-0 data-[side=bottom]:data-open:slide-in-from-bottom-10 data-[side=left]:data-open:slide-in-from-left-10 data-[side=right]:data-open:slide-in-from-right-10 data-[side=top]:data-open:slide-in-from-top-10 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-[side=bottom]:data-closed:slide-out-to-bottom-10 data-[side=left]:data-closed:slide-out-to-left-10 data-[side=right]:data-closed:slide-out-to-right-10 data-[side=top]:data-closed:slide-out-to-top-10",
          className
        )}
        {...props}
      >
        {children}
        {/* 밀어 닫기가 Esc·스크림·닫기 X 와 같은 Radix 닫기 경로를 타게 하는 숨은 단추 — `SheetContent` 는 열림
            상태를 갖지 않아(Root 가 가진다) 닫기를 직접 부를 수 없다. 같은 경로라 닫힌 뒤 포커스도 트리거로 돌아간다.
            `hidden` 이라 포커스 순회와 보조기기에서 빠진다. */}
        {isSwipeable && (
          <SheetPrimitive.Close ref={swipeCloseRef} hidden tabIndex={-1} />
        )}
        {showCloseButton && (
          <SheetPrimitive.Close data-slot="sheet-close" asChild>
            {/* ghost의 `hover:bg-muted`는 popover 표면과 같은 값이라 사라진다 — 호출부가 못 덮는 자리라 여기서 secondary로 덮는다. */}
            <Button
              variant="ghost"
              className="absolute top-3 right-3 hover:bg-secondary aria-expanded:bg-secondary"
              size="icon-sm"
            >
              <XIcon
              />
              <span className="sr-only">닫기</span>
            </Button>
          </SheetPrimitive.Close>
        )}
      </SheetPrimitive.Content>
    </SheetPortal>
  )
}

function setRef<T>(ref: React.Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") ref(value)
  else if (ref) ref.current = value
}

/**
 * 왼쪽 시트를 왼쪽으로 밀어 닫는 손짓(터치·펜·마우스). 판정 수치는 `sheet-swipe` 의 순수 함수가 정하고, 여기서는
 * 포인터 흐름을 그 함수에 잇고 시트를 옮긴다. 시트 요소에 직접 단 처리기라 떼는 함수를 돌려준다.
 *
 * - **시작**: 첫 포인터의 주 버튼 누름만 본다. 10px 를 움직인 순간 왼쪽 가로 이동이면 끌기이고, 아니면 그 누름이
 *   끝날 때까지 보지 않는다(세로 스크롤과 두 손가락 확대는 `touch-action: pan-y pinch-zoom` 으로 브라우저가
 *   맡는다 — 확대를 빼면 드로어 위에서 글자를 키울 수 없다). 끌기가 시작되면 포인터를 잡아 시트 밖까지 따라가고,
 *   마우스로 시작된 글자 선택을 지운다.
 * - **판정에서 빼는 요소 없음**: 누른 대상과 무관하게 모든 누름을 본다. 지금 왼쪽 시트 내용(링크·버튼·글)에는
 *   괜찮지만, 글 입력칸·가로 스크롤 요소·끌어 놓기를 왼쪽 시트에 넣으면 그 요소에서 시작한 누름을 판정에서 빼는
 *   처리를 함께 넣어야 한다(아니면 글자 고르기·가로 스크롤이 시트 끌기로 바뀐다).
 * - **따라오기**: CSS 개별 속성 `translate` 로 옮긴다. 열림·닫힘 키프레임은 `transform` 을 움직여 둘이 겹치지 않고
 *   더해지므로, 닫힘 애니메이션이 끌던 자리에서 이어진다. 끄는 동안은 전이를 끈다. 손을 따라오는 이동은 직접 조작이라
 *   `prefers-reduced-motion` 에서도 남는다.
 * - **놓기**: 닫히면 숨은 닫기 단추를 눌러 Radix 닫기 경로를 탄다. 돌아가면 남은 거리에 비례한 시간으로 맞춰
 *   들어가고, `prefers-reduced-motion: reduce` 면 즉시 제자리다(닫힘 애니메이션은 클래스의 `motion-safe:` 가 같은
 *   조건으로 끈다). 브라우저가 누름을 가져가면(`pointercancel`) 돌아간다.
 * - **click**: 끌기로 끝난 뗌 직후의 포인터 click 한 번을 막는다 — 링크 위에서 시작한 끌기가 그 링크로 이동하지
 *   않게. Chrome 에서는 포인터를 잡아 둔 덕에 그 click 이 시트로 가 링크가 받지 않는 것을 확인했지만, 다른
 *   브라우저는 확인하지 않아 막는 것을 둔다. 끌기가 시작되지 않은 누름의 click 은 그대로다.
 * - **dragstart**: 늘 막는다. 링크·글자를 마우스로 누른 채 움직이면 브라우저의 끌어 놓기가 끌기 판정(10px)보다
 *   먼저 시작될 수 있고, 시작되면 포인터 흐름을 가로챈다.
 */
function attachSwipeToClose(sheet: HTMLElement, close: () => void): () => void {
  let press:
    | { pointerId: number; x: number; y: number; state: SheetSwipeStart }
    | undefined
  let samples: PointerSample[] = []
  let suppressedAt: number | undefined
  let offset = 0

  function moveTo(px: number) {
    offset = px
    sheet.style.transition = "none"
    sheet.style.translate = `${px}px 0`
  }

  function clearMove() {
    offset = 0
    sheet.style.transition = ""
    sheet.style.translate = ""
  }

  function settle() {
    const durationMs = toSheetSettleDurationMs({
      remainingPx: offset,
      sheetWidth: sheet.offsetWidth,
    })
    const isReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
    if (isReduced || durationMs === 0 || offset === 0) {
      clearMove()
      return
    }
    offset = 0
    sheet.style.transition = `translate ${durationMs}ms ease-out`
    sheet.style.translate = "0px 0"
  }

  function handlePointerDown(event: PointerEvent) {
    if (!event.isPrimary || event.button !== 0) return
    press = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      state: "pending",
    }
    samples = [{ x: event.clientX, time: event.timeStamp }]
  }

  function handlePointerMove(event: PointerEvent) {
    if (press === undefined || event.pointerId !== press.pointerId) return
    // 시트 밖(스크림 위)에서 마우스를 놓아 뗌을 받지 못한 누름 — 버튼 없이 움직이는 마우스를 따라가지 않는다.
    if (event.pointerType === "mouse" && (event.buttons & 1) === 0) {
      handlePointerCancel(event)
      return
    }
    if (press.state === "ignore") return
    const dx = event.clientX - press.x
    samples.push({ x: event.clientX, time: event.timeStamp })
    while (
      samples.length > 2 &&
      event.timeStamp - (samples[0]?.time ?? event.timeStamp) >
        SHEET_SWIPE_VELOCITY_WINDOW_MS
    ) {
      samples.shift()
    }
    if (press.state === "pending") {
      press.state = toSheetSwipeStart({ dx, dy: event.clientY - press.y })
      if (press.state !== "drag") return
      sheet.setPointerCapture(event.pointerId)
      sheet.style.userSelect = "none"
      window.getSelection()?.removeAllRanges()
    }
    moveTo(toSheetSwipeOffset(dx))
  }

  function handlePointerUp(event: PointerEvent) {
    if (press === undefined || event.pointerId !== press.pointerId) return
    const isDrag = press.state === "drag"
    const dx = event.clientX - press.x
    press = undefined
    sheet.style.userSelect = ""
    if (!isDrag) return
    const release = toSheetSwipeRelease({
      dx,
      velocityX: toReleaseVelocity(samples, {
        x: event.clientX,
        time: event.timeStamp,
      }),
      sheetWidth: sheet.offsetWidth,
    })
    if (release === "close") close()
    else settle()
    // 닫기 단추를 누르는 click 이 이 표시를 먼저 지우지 않게 닫은 뒤에 남긴다.
    suppressedAt = event.timeStamp
  }

  function handlePointerCancel(event: PointerEvent) {
    if (press === undefined || event.pointerId !== press.pointerId) return
    const isDrag = press.state === "drag"
    press = undefined
    sheet.style.userSelect = ""
    if (isDrag) settle()
  }

  function handleTransitionEnd(event: TransitionEvent) {
    const isSettled =
      event.target === sheet &&
      event.propertyName === "translate" &&
      offset === 0
    if (isSettled) clearMove()
  }

  function handleClickCapture(event: MouseEvent) {
    const at = suppressedAt
    suppressedAt = undefined
    const isSuppressed = shouldSuppressClickAfterSwipe({
      suppressedAt: at,
      clickAt: event.timeStamp,
      detail: event.detail,
    })
    if (!isSuppressed) return
    event.preventDefault()
    event.stopPropagation()
  }

  function handleDragStart(event: DragEvent) {
    event.preventDefault()
  }

  sheet.addEventListener("pointerdown", handlePointerDown)
  sheet.addEventListener("pointermove", handlePointerMove)
  sheet.addEventListener("pointerup", handlePointerUp)
  sheet.addEventListener("pointercancel", handlePointerCancel)
  sheet.addEventListener("transitionend", handleTransitionEnd)
  sheet.addEventListener("click", handleClickCapture, true)
  sheet.addEventListener("dragstart", handleDragStart)
  return () => {
    sheet.removeEventListener("pointerdown", handlePointerDown)
    sheet.removeEventListener("pointermove", handlePointerMove)
    sheet.removeEventListener("pointerup", handlePointerUp)
    sheet.removeEventListener("pointercancel", handlePointerCancel)
    sheet.removeEventListener("transitionend", handleTransitionEnd)
    sheet.removeEventListener("click", handleClickCapture, true)
    sheet.removeEventListener("dragstart", handleDragStart)
  }
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-header"
      className={cn("flex flex-col gap-0.5 p-4", className)}
      {...props}
    />
  )
}

function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn("mt-auto flex flex-col gap-2 p-4", className)}
      {...props}
    />
  )
}

function SheetTitle({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      data-slot="sheet-title"
      className={cn(
        "font-heading text-lg font-medium text-foreground",
        className
      )}
      {...props}
    />
  )
}

function SheetDescription({
  className,
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      data-slot="sheet-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetFooter,
  SheetTitle,
  SheetDescription,
}
