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
      {/* `[&>*]:min-w-0` — grid item의 기본 `min-width:auto`는 min-content로 작동해서, 표처럼
          넓은 콘텐츠가 든 자식이 그리드 트랙 자체를 부풀린다(`max-w-*`는 바깥 박스만 묶을 뿐 안쪽
          트랙엔 안 걸린다). 대안인 `grid-cols-[minmax(0,1fr)]`(트랙에 직접 `min:0`)도 같은 폭에서
          동일하게 고쳤지만(1280px·390px 실측 scrollWidth 2500→clientWidth와 동일), `cn()`이
          tailwind-merge를 쓰는 탓에 호출부가 `grid-cols-*`를 얹으면 그 기저 클래스를 통째로
          지워 버그가 조용히 되살아난다(twMerge 실측: `grid-cols-[minmax(0,1fr)]` + 호출부
          `grid-cols-2` → 전자가 삭제됨). 자식 선택자는 그런 충돌이 없어 이쪽을 택했다. */}
      {/* `has-data-[slot=dialog-body]:` — 자손에 `DialogBody`가 있을 때만 이 상자가 최대 높이가 있는
          flex 컬럼이 되어 헤더·푸터는 제자리에 두고 본문만 스크롤한다. prop으로 켜게 하지 않은 이유:
          prop을 잊고 `DialogBody`만 쓰면 grid 안의 `flex-1 min-h-0`이 무효라 최대 높이가 없어지고,
          Radix가 body 스크롤을 잠근 채로 화면 밖으로 밀린 본문·푸터에 닿을 길이 조용히 사라진다.
          `:has()`는 쓰는 순간 레이아웃이 같이 오므로 잊을 것이 없다. `DialogBody`가 없는 다이얼로그는
          선택자가 거짓이라 계산값이 전과 같다(grid, 최대 높이 없음). 변형 선택자의 특이도(0,2,0)가
          기본 `grid`(0,1,0)를 이기므로, 상한을 바꾸려는 호출부도 평범한 `max-h-*`가 아니라 같은 변형
          `has-data-[slot=dialog-body]:max-h-*`로 적어야 한다. 이 상자에 `overflow-hidden`을 걸지 않는
          것은 댓글 멘션 팝업이 이 상자를 기준으로 absolute 배치되기 때문이다. */}
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          "group/dialog-content fixed top-1/2 left-1/2 z-50 grid w-full max-w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-xl bg-popover p-4 text-sm text-popover-foreground ring-1 ring-foreground/10 motion-safe:duration-100 outline-none sm:max-w-sm motion-safe:data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 motion-safe:data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 has-data-[slot=dialog-body]:flex has-data-[slot=dialog-body]:max-h-dialog has-data-[slot=dialog-body]:flex-col [&>*]:min-w-0",
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
            {/* ghost의 `hover:bg-muted`는 popover 표면과 같은 값이라 사라진다 — 호출부가 못 덮는 자리라 여기서 secondary로 덮는다. */}
            <Button
              variant="ghost"
              className="absolute top-2 right-2 hover:bg-secondary aria-expanded:bg-secondary"
              size="icon-sm"
            >
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

/** 본문이 스크롤하는 다이얼로그(`DialogBody`가 있는 다이얼로그)에서만 오른쪽에 `pr-8`을 둔다 —
 * 닫기 X(`top-2 right-2`, 32px)가 헤더 첫 줄과 같은 높이에 앉으므로, 헤더 글자가 X 앞 8px에서 끝나게
 * 하려는 것이다. 모든 헤더에 주지 않는 이유는 설명 문단 폭도 32px 줄어 본문 없는 짧은 확인 모달의
 * 줄바꿈과 높이가 바뀌기 때문이다. */
function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn(
        "flex flex-col gap-2 group-has-data-[slot=dialog-body]/dialog-content:pr-8",
        className
      )}
      {...props}
    />
  )
}

/** 고정 헤더와 고정 푸터 사이에서 혼자 스크롤하는 본문 슬롯. 이것을 넣으면 `DialogContent`가 알아서
 * 최대 높이가 있는 flex 컬럼이 된다. 자식이 둘 이상이면 이 상자는 `flex`·`gap`이 없는 블록이라 간격이
 * 0으로 붙는다 — 그때는 호출부가 `className="flex flex-col gap-4"`를 준다(단일 자식의 배치를 바꾸지
 * 않으려고 기본값에 넣지 않았다).
 *
 * - `-mx-4 px-4`: 스크롤포트를 다이얼로그 전폭으로 넓힌다. 다이얼로그의 16px 패딩 안에서 끝나던
 *   음수 마진 링크의 hover 면, 옆으로 미는 진입 애니메이션, 가장자리 컨트롤의 포커스 링이 스크롤러에
 *   잘리거나 가로 스크롤바를 만들지 않고, 스크롤바도 다이얼로그 오른쪽 끝에 붙는다.
 * - `overflow-x-hidden`: `overflow-y:auto`만 주면 x도 auto로 계산되어 순간적인 가로 넘침이 가로
 *   스크롤바를 깜빡인다.
 * - `border-t`: 헤더와 본문의 경계선이다. 헤더의 `border-b`가 아니라 여기 둔 이유는 이 상자가 이미
 *   전폭이라 선이 `DialogFooter`의 선처럼 다이얼로그 양 끝에 닿고, 선이 곧 스크롤 영역의 위 모서리라
 *   올라간 내용이 정확히 선에서 잘리기 때문이다. 그래서 이 슬롯은 헤더 아래에 오는 것을 전제한다.
 * - `pt-4`, `pb-1 -mb-1`: 선 아래 16px은 선 위 `gap-4`와 대칭이다. 바닥 4px은 마지막 컨트롤의 포커스
 *   링 여유이고, 같은 만큼 바깥으로 당겨 보이는 간격(푸터 선까지·다이얼로그 바닥까지 16px)은 그대로 둔다.
 *
 * `scrollLabel`을 주면 본문 자체가 Tab 정지(`tabIndex=0`)가 되고 그 이름의 region으로 읽힌다. 닫기 X가
 * 본문 밖에 있으니 본문에 포커스 요소가 없으면 키보드로 본문을 스크롤할 길이 없어서다. 켜기와 이름을
 * 한 prop으로 묶어 이름 없는 Tab 정지를 만들 수 없게 했고, 이름은 다이얼로그 제목과 겹치지 않게
 * "무엇이 스크롤되는가"로 준다. 포커스 표시가 하우스 레시피(바깥 `ring-3`)가 아니라 안쪽 outline인
 * 이유: 전폭인 이 상자의 바깥 링은 다이얼로그 밖 스크림 위에 그려지고, inset box-shadow는 스크롤하는
 * 내용(그림 칸 등)에 덮인다. outline은 자손 위에 그려지고 2px 안쪽으로 들어온다. */
function DialogBody({
  className,
  scrollLabel,
  ...props
}: React.ComponentProps<"div"> & {
  /** 주면 본문이 Tab 정지가 되고 이 이름으로 읽힌다 — 본문에 포커스 요소가 없을 수 있는 다이얼로그용. */
  scrollLabel?: string
}) {
  return (
    <div
      data-slot="dialog-body"
      {...(scrollLabel !== undefined && {
        tabIndex: 0,
        role: "region",
        "aria-label": scrollLabel,
      })}
      className={cn(
        "-mx-4 -mb-1 min-h-0 flex-1 overflow-x-hidden overflow-y-auto border-t px-4 pt-4 pb-1 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
        className
      )}
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
 * 되돌리려면 `sm` 이상까지 함께 뒤집어야 한다.
 *
 * 띠 채움은 상류의 `bg-muted/50`이 아니라 `bg-secondary/50`이다 — `muted`는 이 푸터가 앉는
 * `popover`와 같은 값이라 띠가 1.0000:1로 사라진다(DESIGN.md Colors 절 "표면 위 채움"). 알파를 50으로
 * 남긴 이유: 불투명 `secondary`면 그 위 outline 버튼의 `border-input`이 3:1 아래(라이트 2.97 /
 * 다크 2.83)로, `muted-foreground` 글자가 4.5:1 아래(라이트 4.29)로 떨어진다. `/50`은 3.14 / 3.04,
 * 4.53 / 5.78로 둘 다 지킨다(`shadcn add dialog`로 재생성하면 `bg-muted/50`이 되돌아온다). */
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
        "-mx-4 -mb-4 flex flex-col gap-2 rounded-b-xl border-t bg-secondary/50 p-4 sm:flex-row sm:justify-end",
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
      className={cn("font-heading text-lg leading-none font-medium", className)}
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
  DialogBody,
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
