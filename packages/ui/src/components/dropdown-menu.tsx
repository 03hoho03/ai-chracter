import * as React from "react"
import { DropdownMenu as DropdownMenuPrimitive } from "radix-ui"

import { cn } from "@ai-character-chat/ui/lib/utils"
import { CheckIcon, ChevronRightIcon } from "lucide-react"

function DropdownMenu({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Root>) {
  return <DropdownMenuPrimitive.Root data-slot="dropdown-menu" {...props} />
}

function DropdownMenuPortal({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Portal>) {
  return (
    <DropdownMenuPrimitive.Portal data-slot="dropdown-menu-portal" {...props} />
  )
}

function DropdownMenuTrigger({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Trigger>) {
  return (
    <DropdownMenuPrimitive.Trigger
      data-slot="dropdown-menu-trigger"
      {...props}
    />
  )
}

/** **아래에 더 있는 동안 콘텐츠 하단을 `::after` 그라디언트로 흐린다(`data-clipped-below`).** `max-h-(--radix-…-available-height)`가
 * 뷰포트를 넘는 메뉴를 자르는데, macOS·iOS의 오버레이 스크롤바에는 상시 표시가 없어 잘렸다는 신호가
 * 하나도 없다 — 가로 폰(844×390)에서 368px짜리 헤더 프로필 메뉴가 342px로 잘려 `로그아웃` 글자가
 * **0/16px**인데 메뉴는 구분선에서 끊겨 **완결된 메뉴처럼 보였다**(`scrollTop: 0` 실측).
 *
 * 처방을 고를 때 세 후보를 실측으로 떨어뜨렸다. (1) **상시 스크롤바**: `scrollbar-width`·
 * `scrollbar-color`만으로는 이 환경에서 오버레이가 안 풀린다(gutter가 계속 0px). `::-webkit-scrollbar`를
 * 스타일하면 풀리지만(gutter 6px) 그건 iOS Safari에서 무시된다 — **결함이 나는 기기가 바로 폰이다.**
 * (2) **스크롤 섀도**: 다크(`popover` 0.210)에서 어두운 그림자는 보이지 않는다 — DESIGN.md가 "어두운
 * 방에서 드리운 그림자는 보이지도 않는다"로 이미 기각해 둔 수단이다. (3) **24px 페이드**: 잘린 자리에
 * 구분선과 6px 조각밖에 없어서 **바탕만 흐려지고 신호가 안 생겼다**(스크린샷 A/B에서 원본과 구별 불가).
 * 그래서 32px다 — **마지막 온전한 항목까지 물어야** 글자가 흐려지면서 "아래가 더 있다"가 읽힌다.
 *
 * **높이는 대비가 정한다.** 이 페이드는 밴드에 든 글자를 흐리므로 그 글자가 AA 아래로 가면 안 된다.
 * 위 기하(마지막 온전한 항목의 글리프 하단이 메뉴 바닥에서 22px)에서 40px면 α가 0.45까지 올라
 * **라이트 3.8286으로 미달**이고 다크는 5.1434로 통과한다 — **두 테마를 다 재야 잡히는 결함이다.**
 * 32px면 α 0.313에서 **라이트 5.8570 / 다크 7.3803**이다(안 흐린 값 라이트 15.7988 / 다크 14.4917).
 * 그 아래 24px는 위에서 본 대로 신호가 안 생긴다. 잘리는 위치가 달라 온전한 행의 글자가 밴드에 더
 * 깊이 들어오면 그 행은 더 흐려진다 — 스크롤로 닿는 행이고, 신호가 아예 없는 쪽보다 낫다고 봤다.
 *
 * 위쪽은 안 한다: 위가 잘리는 건 사용자가 **직접 스크롤한 뒤**라 이미 스크롤 가능함을 안다. */
function DropdownMenuContent({
  className,
  align = "start",
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Content>) {
  const [clippedBelow, setClippedBelow] = React.useState(false)

  // `useEffect`가 아니라 콜백 ref다 — 이 컴포넌트는 메뉴가 **닫혀 있을 때도** 마운트돼 있고
  // (Portal이 열릴 때만 실제 노드를 만든다) 그래서 마운트 시점의 ref는 언제나 null이다.
  // 콜백 ref는 노드가 실제로 붙는 순간 불린다(정리 함수 반환은 React 19).
  const contentRef = React.useCallback((content: HTMLDivElement | null) => {
    if (!content) return

    const update = () =>
      setClippedBelow(
        content.scrollHeight - content.scrollTop - content.clientHeight > 1
      )
    // 관찰 시작 시점에 한 번 발화하므로 첫 측정도 이 한 줄이 겸한다.
    const observer = new ResizeObserver(update)
    observer.observe(content)
    content.addEventListener("scroll", update)
    return () => {
      observer.disconnect()
      content.removeEventListener("scroll", update)
    }
  }, [])

  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        ref={contentRef}
        data-slot="dropdown-menu-content"
        data-clipped-below={clippedBelow}
        sideOffset={sideOffset}
        align={align}
        className={cn("z-50 max-h-(--radix-dropdown-menu-content-available-height) w-(--radix-dropdown-menu-trigger-width) min-w-32 origin-(--radix-dropdown-menu-content-transform-origin) overflow-x-hidden overflow-y-auto rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 motion-safe:duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-[clipped-below=true]:after:pointer-events-none data-[clipped-below=true]:after:sticky data-[clipped-below=true]:after:bottom-0 data-[clipped-below=true]:after:-mt-8 data-[clipped-below=true]:after:block data-[clipped-below=true]:after:h-8 data-[clipped-below=true]:after:bg-linear-to-t data-[clipped-below=true]:after:from-popover data-[state=closed]:overflow-hidden motion-safe:data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95", className )}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  )
}

function DropdownMenuGroup({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Group>) {
  return (
    <DropdownMenuPrimitive.Group data-slot="dropdown-menu-group" {...props} />
  )
}

/** **포커스 표시는 채움이 아니라 링이 진다**(US-004). 상류 shadcn은 `outline-hidden` + `focus:bg-accent`
 * 하나로 끝내는데, 이 시스템의 명도 사다리에서 그 채움 변화는 popover 대비 **1.1439 다크 / 1.1239 라이트**
 * (destructive 항목은 1.1119 / 1.1598)로 WCAG 1.4.11(3:1)의 절반도 안 된다. 사다리로는 못 고친다 —
 * 최상단 `border`를 채움으로 써도 popover 대비 약 1.3이다. 그래서 `focus:inset-ring-1 focus:inset-ring-ring`을
 * 얹었다: 링(=`primary`) 대 포커스 채움이 중립 **5.7320 / 5.4691**, destructive **5.8968 / 5.2997**로
 * 두 variant 모두 한 번에 넘긴다(그래서 링 색을 variant별로 가르지 않는다 — 메뉴 안에서 포커스 어휘가 하나다).
 *
 * **`Item`·`CheckboxItem`·`RadioItem`·`SubTrigger` 넷을 함께 고친 것은 의도다** — 넷이 같은
 * `outline-hidden focus:bg-accent`를 물고 전원 미달이라 "결함 없는 소비처"가 0개고, 한 곳만 고치면
 * 앱 안에서 포커스 시각 언어가 갈린다. Radix는 `pointermove`에도 focus를 걸므로 이 링은 키보드 전용이 아니다.
 *
 * `data-disabled:opacity-65`는 상류 `opacity-50`을 올린 값이다 — 50%면 항목 글자가 popover 위에서
 * **3.2515 라이트 / 4.4959 다크**로 AA(4.5:1) 아래인데, 이 앱은 비활성 항목에 "왜 못 누르는지"를
 * 읽혀야 하는 자리가 있다(이용제한 작품 메뉴). 65%면 **5.1882 / 6.7086**이다.
 *
 * **`aria-disabled:`가 같은 값을 함께 받는 것도 그 자리 때문이다**(US-008). Radix는 `disabled` 항목을
 * `RovingFocusGroup.Item`의 `focusable: !disabled`로 포커스 순회와 타입어헤드에서 통째로 빼므로,
 * 사유를 읽혀야 하는 비활성 항목은 `disabled` 대신 `aria-disabled` + `onSelect` `preventDefault`로 만든다
 * (`VisibilityTransitionMenuItems`). 그러면 `data-disabled`가 안 붙어 흐림이 사라지므로 두 선택자가
 * 같은 값을 물어야 한다. `pointer-events-none`은 일부러 안 걸었다 — 포커스와 hover가 살아 있어야
 * 그 자리에서 사유가 읽힌다. */
function DropdownMenuItem({
  className,
  inset,
  variant = "default",
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Item> & {
  inset?: boolean
  variant?: "default" | "destructive"
}) {
  return (
    <DropdownMenuPrimitive.Item
      data-slot="dropdown-menu-item"
      data-inset={inset}
      data-variant={variant}
      className={cn(
        "group/dropdown-menu-item relative flex cursor-default items-center gap-1.5 rounded-md px-1.5 py-1 text-sm outline-hidden select-none focus:inset-ring-1 focus:inset-ring-ring focus:bg-accent focus:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground data-inset:pl-7 data-[variant=destructive]:text-destructive-text data-[variant=destructive]:focus:bg-destructive/10 data-[variant=destructive]:focus:text-destructive-text data-disabled:pointer-events-none data-disabled:opacity-65 aria-disabled:opacity-65 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 data-[variant=destructive]:*:[svg]:text-destructive-text",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuCheckboxItem({
  className,
  children,
  checked,
  inset,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.CheckboxItem> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.CheckboxItem
      data-slot="dropdown-menu-checkbox-item"
      data-inset={inset}
      className={cn(
        "relative flex cursor-default items-center gap-1.5 rounded-md py-1 pr-8 pl-1.5 text-sm outline-hidden select-none focus:inset-ring-1 focus:inset-ring-ring focus:bg-accent focus:text-accent-foreground focus:**:text-accent-foreground data-inset:pl-7 data-disabled:pointer-events-none data-disabled:opacity-65 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      checked={checked}
      {...props}
    >
      <span
        className="pointer-events-none absolute right-2 flex items-center justify-center"
        data-slot="dropdown-menu-checkbox-item-indicator"
      >
        <DropdownMenuPrimitive.ItemIndicator>
          <CheckIcon
          />
        </DropdownMenuPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownMenuPrimitive.CheckboxItem>
  )
}

function DropdownMenuRadioGroup({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.RadioGroup>) {
  return (
    <DropdownMenuPrimitive.RadioGroup
      data-slot="dropdown-menu-radio-group"
      {...props}
    />
  )
}

function DropdownMenuRadioItem({
  className,
  children,
  inset,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.RadioItem> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.RadioItem
      data-slot="dropdown-menu-radio-item"
      data-inset={inset}
      className={cn(
        "relative flex cursor-default items-center gap-1.5 rounded-md py-1 pr-8 pl-1.5 text-sm outline-hidden select-none focus:inset-ring-1 focus:inset-ring-ring focus:bg-accent focus:text-accent-foreground focus:**:text-accent-foreground data-inset:pl-7 data-disabled:pointer-events-none data-disabled:opacity-65 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      <span
        className="pointer-events-none absolute right-2 flex items-center justify-center"
        data-slot="dropdown-menu-radio-item-indicator"
      >
        <DropdownMenuPrimitive.ItemIndicator>
          <CheckIcon
          />
        </DropdownMenuPrimitive.ItemIndicator>
      </span>
      {children}
    </DropdownMenuPrimitive.RadioItem>
  )
}

function DropdownMenuLabel({
  className,
  inset,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Label> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.Label
      data-slot="dropdown-menu-label"
      data-inset={inset}
      className={cn(
        "px-1.5 py-1 text-xs font-medium text-muted-foreground data-inset:pl-7",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuSeparator({
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Separator>) {
  return (
    <DropdownMenuPrimitive.Separator
      data-slot="dropdown-menu-separator"
      className={cn("-mx-1 my-1 h-px bg-border", className)}
      {...props}
    />
  )
}

function DropdownMenuShortcut({
  className,
  ...props
}: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="dropdown-menu-shortcut"
      className={cn(
        "ml-auto text-xs tracking-widest text-muted-foreground group-focus/dropdown-menu-item:text-accent-foreground",
        className
      )}
      {...props}
    />
  )
}

function DropdownMenuSub({
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.Sub>) {
  return <DropdownMenuPrimitive.Sub data-slot="dropdown-menu-sub" {...props} />
}

function DropdownMenuSubTrigger({
  className,
  inset,
  children,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.SubTrigger> & {
  inset?: boolean
}) {
  return (
    <DropdownMenuPrimitive.SubTrigger
      data-slot="dropdown-menu-sub-trigger"
      data-inset={inset}
      className={cn(
        "flex cursor-default items-center gap-1.5 rounded-md px-1.5 py-1 text-sm outline-hidden select-none focus:inset-ring-1 focus:inset-ring-ring focus:bg-accent focus:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground data-inset:pl-7 data-open:bg-accent data-open:text-accent-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    >
      {children}
      <ChevronRightIcon className="ml-auto" />
    </DropdownMenuPrimitive.SubTrigger>
  )
}

function DropdownMenuSubContent({
  className,
  ...props
}: React.ComponentProps<typeof DropdownMenuPrimitive.SubContent>) {
  return (
    <DropdownMenuPrimitive.SubContent
      data-slot="dropdown-menu-sub-content"
      className={cn("z-50 min-w-[96px] origin-(--radix-dropdown-menu-content-transform-origin) overflow-hidden rounded-lg bg-popover p-1 text-popover-foreground shadow-lg ring-1 ring-foreground/10 motion-safe:duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 motion-safe:data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95", className )}
      {...props}
    />
  )
}

export {
  DropdownMenu,
  DropdownMenuPortal,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
}
