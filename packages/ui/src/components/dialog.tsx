import * as React from "react"
import { Dialog as DialogPrimitive } from "radix-ui"
import { XIcon } from "lucide-react"

import { cn } from "@ai-character-chat/ui/lib/utils"
import { Button } from "@ai-character-chat/ui/components/button"

function Dialog({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogTrigger({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogPortal({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogClose({
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 isolate z-50 bg-black/10 motion-safe:duration-100 supports-backdrop-filter:backdrop-blur-xs motion-safe:data-open:animate-in data-open:fade-in-0 motion-safe:data-closed:animate-out data-closed:fade-out-0",
        className
      )}
      {...props}
    />
  )
}

function DialogContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  showCloseButton?: boolean
}) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl bg-popover p-4 text-sm text-popover-foreground ring-1 ring-foreground/10 motion-safe:duration-100 outline-none sm:max-w-sm motion-safe:data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        {...props}
      >
        {/* 닫기 버튼은 화면에서 **제일 위**(`top-2 right-2`)에 있으므로 DOM에서도 제일 앞이다.
            상류 shadcn은 `{children}` 뒤에 두는데, 그러면 절대배치라 렌더는 맨 위인데 탭 순서는 맨
            뒤가 되어 포커스가 화면을 거슬러 올라간다(320px 실측: `취소` y475 → `편집한 내용 버리기`
            y435 → `닫기` y330 — WCAG 1.3.2/2.4.3). 렌더는 절대배치라 1픽셀도 안 바뀌고 순서만 바뀐다.
            **부수효과는 초기 포커스뿐이다**: Radix FocusScope는 첫 tabbable을 잡으므로 이제 이 버튼이
            받는다(전에는 `취소`). 확인 모달에서는 어느 쪽이든 안전한 컨트롤이다. **호출부의
            `autoFocus`는 그대로 이긴다** — FocusScope가 `container.contains(document.activeElement)`면
            자기 로직을 통째로 건너뛰기 때문이다(`react-focus-scope` 소스 확인 + `autoFocus` 인풋을
            넣은 임시 다이얼로그로 실측). admin `DeleteConfirmModal`이 이 경로에 있다. */}
        {showCloseButton && (
          <DialogPrimitive.Close data-slot="dialog-close" asChild>
            <Button variant="ghost" className="absolute top-2 right-2" size="icon-sm">
              <XIcon />
              <span className="sr-only">닫기</span>
            </Button>
          </DialogPrimitive.Close>
        )}
        {children}
      </DialogPrimitive.Content>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    />
  )
}

/** **좁은 화면에서 `flex-col`이다 — 상류 shadcn의 `flex-col-reverse`가 아니다.**
 * `flex-col-reverse`는 시각 순서만 뒤집고 DOM 순서는 그대로 둬서 탭 순서가 화면을 거슬러 올라간다
 * (320px 실측: `취소` y475 → `편집한 내용 버리기` y435 — WCAG 1.3.2/2.4.3). DOM 순서는 반응형이 될
 * 수 없으므로 두 폭 중 하나를 골라야 하는데, `sm` 이상의 `취소 왼쪽 · 실행 오른쪽`을 그대로 두려면
 * DOM이 `[취소, 실행]`이어야 하고 그러면 좁은 화면의 세로 배치는 `취소` 위 · 실행 아래로 정해진다.
 * 즉 "확인 버튼이 위"는 접근성과 맞바꿀 수 있는 취향이 아니라 이 DOM 순서가 배제하는 배치다.
 * 되돌리려면 `sm` 이상까지 함께 뒤집어야 한다. */
function DialogFooter({
  className,
  showCloseButton = false,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  showCloseButton?: boolean
}) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "-mx-4 -mb-4 flex flex-col gap-2 rounded-b-xl border-t bg-muted/50 p-4 sm:flex-row sm:justify-end",
        className
      )}
      {...props}
    >
      {children}
      {showCloseButton && (
        <DialogPrimitive.Close asChild>
          <Button variant="outline">닫기</Button>
        </DialogPrimitive.Close>
      )}
    </div>
  )
}

function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("font-heading text-base leading-none font-medium", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn(
        "text-sm text-muted-foreground *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-foreground",
        className
      )}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
}
