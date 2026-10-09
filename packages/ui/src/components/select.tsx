import * as React from "react"
import { Select as SelectPrimitive } from "radix-ui"
import { ChevronDownIcon, CheckIcon } from "lucide-react"

import { cn } from "@ai-character-chat/ui/lib/utils"

function Select({
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Root>) {
  return <SelectPrimitive.Root data-slot="select" {...props} />
}

function SelectGroup({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Group>) {
  return (
    <SelectPrimitive.Group
      data-slot="select-group"
      className={cn("scroll-my-1", className)}
      {...props}
    />
  )
}

function SelectValue({
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />
}

function SelectTrigger({
  className,
  size = "default",
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger> & {
  size?: "sm" | "default"
}) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      data-size={size}
      /** `button.tsx`/`toggle.tsx`의 `default`/`sm`과 맞춘다.
       * `pr-2 pl-2.5`는 원래 `Button`의 `default`+trailing-icon 조합(베이스 `px-2.5`, 아이콘
       * 보정 `pr-2`)을 그대로 옮긴 값이었다 — 셰브런이 항상 붙는 트리거라 그 조합을 계속 따라간다.
       * 새 베이스도 같은 관계로: 베이스 쪽(`pl`)은 `Button` `default`의 새 `px-4`(16px), 아이콘
       * 쪽(`pr`)은 그 보정값 `pr-3.5`(14px). `py-2`는 걷어냈다 — `Button`/`Toggle`도 세로 패딩이
       * 없고 `h-*` + `items-center`만으로 세로 중앙정렬을 하므로, 세 프리미티브가 같은 높이 티어에서
       * 시각적으로 같아지려면 이 프리미티브만 패딩으로 높이를 만들면 안 된다.
       * `data-[size=sm]:rounded-[min(var(--radius-md),10px)]` 캡도 같은 이유로 걷었다 — `sm`이
       * 32px 티어로 올라가면 `default`와 같은 32px 안에서 모서리가 갈리게 된다. */
      className={cn(
        "flex w-fit items-center justify-between gap-1.5 rounded-lg border border-input bg-transparent pr-3.5 pl-4 text-sm whitespace-nowrap motion-safe:transition-colors outline-none select-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 data-placeholder:text-muted-foreground data-[size=default]:h-9 data-[size=sm]:h-8 *:data-[slot=select-value]:line-clamp-1 *:data-[slot=select-value]:flex *:data-[slot=select-value]:items-center *:data-[slot=select-value]:gap-1.5 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDownIcon className="pointer-events-none size-4 text-muted-foreground" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  )
}

/** **기본 배치는 `popper`다 — 트리거 바로 아래, 왼쪽 끝을 맞춰 뜬다**(`DropdownMenuContent`와 같은 기하).
 * 상류 기본값 `item-aligned`는 선택된 항목의 글자를 트리거의 값 글자 위에 겹치는데, 그 정렬은 트리거
 * 안 값의 위치에 묶여 있다. 트리거 `pl-4`(16px) 대 항목 `pl-1.5`(6px)라 목록이 약 11px 오른쪽으로 밀려
 * 트리거 왼쪽 가장자리가 뒤로 비쳤고, 값 앞에 축 이름을 둔 트리거(내 작품의 `정렬`)는 그 접두어 폭만큼
 * 더 어긋났다(실측) — 여백을 맞춰도 접두어가 있는 한 고칠 수 없는 구조다.
 *
 * `collisionPadding` 8·`sideOffset` 4도 드롭다운 메뉴와 같은 값이다(뷰포트 끝 0px 밀착 방지). 안쪽
 * 여백은 `Viewport`의 `p-1`이 진다 — 없으면 첫·끝 항목과 포커스 inset 링이 목록 테두리에 맞닿는다.
 *
 * **상류의 위·아래 스크롤 버튼(`SelectScrollUpButton`/`DownButton`)은 두지 않는다.** Radix는 그 버튼을 더
 * 스크롤할 수 있을 때만 마운트하는데, 버튼이 Viewport의 flex 형제(24px)라 경계를 넘는 순간 목록이 휠과
 * 반대 방향으로 24px 튀고, 끝에서는 아래 버튼이 빠지며 최대 스크롤이 줄어 scrollTop이 되감겼다. 포인터가
 * 그 24px 띠에 머물기만 해도 50ms마다 한 항목씩 저절로 스크롤됐다(낮은 창의 장르 목록 실측).
 *
 * **잘림 신호는 그 대신 위·아래 페이드가 진다**(`data-clipped-above`/`data-clipped-below`, 각각 `h-8`·`from-popover`).
 * Radix가 Viewport에 스크롤바를 모든 OS에서 숨기므로(`scrollbar-width: none`) 이것 말고는 신호가 없다.
 * 높이 32px과 그라디언트는 `DropdownMenuContent`의 하단 페이드와 같고, 32px이 대비로 정해진 근거는 그
 * 컴포넌트의 주석에 있다. 드롭다운과 달리 **위쪽에도 페이드를 둔다** — 드롭다운은 위가 잘리는 게 사용자가
 * 직접 스크롤한 뒤뿐이지만, Select는 열 때 Radix가 선택된 항목으로 `scrollIntoView`하므로(popper에서도)
 * 아래쪽 값을 고른 뒤 다시 열면 처음부터 위가 잘린 채 뜬다.
 * 페이드는 음수 마진(`-mb-8`/`-mt-8`)으로 흐름 속 높이가 0이라 켜지고 꺼질 때 항목이 움직이지 않는다.
 *
 * **측정과 `::before`/`::after`는 Content가 아니라 Viewport에 건다** — Radix Content는 flex 컬럼이고 Viewport가
 * `flex:1`로 줄어들며 스크롤하므로, 드롭다운처럼 Content에 걸면 Content는 넘치지 않아 신호가 영영 안 뜬다.
 *
 * Viewport의 `scroll-py-8`은 키보드 이동을 위한 것이다. Radix는 ↑↓·타입어헤드로 옮긴 포커스 항목을
 * `scrollIntoView({ block: "nearest" })`로 따라가는데, 그대로 두면 항목이 위·아래 끝에 붙어 페이드 띠 한가운데서
 * 멈춘다(실측: 아래로 갈 때 글자 하단이 바닥에서 4px). scroll-padding이 그 정렬선을 32px 안쪽으로 당겨
 * 포커스 항목은 늘 띠 밖에 선다. 첫·마지막 항목은 Radix가 scrollTop을 끝까지 보내 그쪽 페이드가 사라진다. */
function SelectContent({
  className,
  children,
  position = "popper",
  align = "start",
  sideOffset = 4,
  collisionPadding = 8,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  const [clipped, setClipped] = React.useState({ above: false, below: false })

  // 콜백 ref다 — Radix는 닫혀 있을 때도 항목 목록을 모으려고 이 Viewport를 DocumentFragment 안에 렌더하고,
  // 열고 닫을 때마다 다른 트리로 갈아 끼워 노드가 바뀐다. 노드가 붙을 때마다 관찰을 새로 건다.
  // Radix가 이 ref를 자기 `onViewportChange`와 합성하므로 의존성 없는 안정된 함수여야 한다.
  const viewportRef = React.useCallback((viewport: HTMLDivElement | null) => {
    if (!viewport) return

    const update = () => {
      const above = viewport.scrollTop > 1
      const below =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight > 1
      setClipped((prev) =>
        prev.above === above && prev.below === below ? prev : { above, below }
      )
    }
    // 열린 뒤 항목이 늘거나 줄어도(비동기로 오는 옵션) Viewport 자신의 크기는 `max-h`에 묶여 그대로일
    // 수 있어 ResizeObserver만으로는 놓친다 — 자식 목록 변화도 함께 본다.
    const resizeObserver = new ResizeObserver(update)
    resizeObserver.observe(viewport)
    const mutationObserver = new MutationObserver(update)
    mutationObserver.observe(viewport, { childList: true, subtree: true })
    viewport.addEventListener("scroll", update)
    return () => {
      resizeObserver.disconnect()
      mutationObserver.disconnect()
      viewport.removeEventListener("scroll", update)
    }
  }, [])

  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        data-slot="select-content"
        data-align-trigger={position === "item-aligned"}
        className={cn(
          "relative z-50 max-h-(--radix-select-content-available-height) min-w-36 origin-(--radix-select-content-transform-origin) overflow-x-hidden overflow-y-auto rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 motion-safe:duration-100 data-[align-trigger=true]:animate-none data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 motion-safe:data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          className
        )}
        position={position}
        align={align}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        {...props}
      >
        <SelectPrimitive.Viewport
          ref={viewportRef}
          data-position={position}
          data-clipped-above={clipped.above}
          data-clipped-below={clipped.below}
          className={cn(
            "scroll-py-8 p-1 data-[position=popper]:h-(--radix-select-trigger-height) data-[position=popper]:w-full data-[position=popper]:min-w-(--radix-select-trigger-width) data-[clipped-below=true]:after:pointer-events-none data-[clipped-below=true]:after:sticky data-[clipped-below=true]:after:bottom-0 data-[clipped-below=true]:after:-mt-8 data-[clipped-below=true]:after:block data-[clipped-below=true]:after:h-8 data-[clipped-below=true]:after:bg-linear-to-t data-[clipped-below=true]:after:from-popover data-[clipped-above=true]:before:pointer-events-none data-[clipped-above=true]:before:sticky data-[clipped-above=true]:before:top-0 data-[clipped-above=true]:before:-mb-8 data-[clipped-above=true]:before:block data-[clipped-above=true]:before:h-8 data-[clipped-above=true]:before:bg-linear-to-b data-[clipped-above=true]:before:from-popover"
          )}
        >
          {children}
        </SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  )
}

function SelectLabel({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Label>) {
  return (
    <SelectPrimitive.Label
      data-slot="select-label"
      className={cn("px-1.5 py-1 text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

function SelectItem({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "relative flex w-full cursor-default items-center gap-1.5 rounded-md py-1 pr-8 pl-1.5 text-sm pointer-coarse:min-h-10 outline-hidden select-none focus:inset-ring-1 focus:inset-ring-ring focus:bg-accent focus:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground data-disabled:pointer-events-none data-disabled:opacity-65 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 *:[span]:last:flex *:[span]:last:items-center *:[span]:last:gap-2",
        className
      )}
      {...props}
    >
      <span className="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <CheckIcon className="pointer-events-none" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  )
}

function SelectSeparator({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Separator>) {
  return (
    <SelectPrimitive.Separator
      data-slot="select-separator"
      className={cn("pointer-events-none -mx-1 my-1 h-px bg-border", className)}
      {...props}
    />
  )
}

export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
}
