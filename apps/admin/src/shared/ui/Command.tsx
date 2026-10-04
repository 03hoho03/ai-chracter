import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Command as CommandPrimitive } from "cmdk";
import { Search } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

// shadcn `Command` 를 이 앱 토큰으로 옮긴 것. web 은 쓰지 않아 `packages/ui` 가 아니라 여기 둔다. 표면이 `popover` 라
// 고른 항목의 채움은 `secondary` 다(`popover` 와 `muted` 는 같은 값이라 `muted` 채움은 사라진다).

export function Command({ className, ...props }: ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn("flex size-full flex-col overflow-hidden bg-popover text-popover-foreground", className)}
      {...props}
    />
  );
}

type CommandDialogProps = Pick<ComponentProps<typeof Dialog>, "open" | "onOpenChange"> &
  Pick<ComponentProps<typeof DialogContent>, "onOpenAutoFocus" | "onCloseAutoFocus"> & {
    /** 화면에는 안 보이는 대화상자 제목·설명(스크린리더가 연 순간 읽는다). */
    title: string;
    description: string;
    children: ReactNode;
  };

/**
 * 공용 `Dialog` 안의 `Command`. cmdk 자체의 대화상자(`Command.Dialog`)를 쓰지 않는 이유는 앱의 다른 모달과 같은 겉모양·
 * 스크림·포커스 규약을 받기 위해서다. 닫기 X 는 두지 않는다 — Esc·바깥 누르기로 닫히고, X 가 있으면 열릴 때 첫 포커스가
 * 입력칸이 아니라 X 로 간다(Radix 는 첫 Tab 정지에 포커스를 준다).
 */
export function CommandDialog({ open, onOpenChange, onOpenAutoFocus, onCloseAutoFocus, title, description, children }: CommandDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="gap-0 overflow-hidden p-0 sm:max-w-lg"
        onOpenAutoFocus={onOpenAutoFocus}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DialogHeader className="sr-only">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {/* 검색어 필터는 호출부가 한다 — 붙여 넣은 ID·이메일처럼 목록에 없는 글자로 만드는 항목이 있어서다. 컨트롤+J/K
            같은 vim 이동은 끈다(팔레트를 여닫는 컨트롤+K 와 겹친다). */}
        <Command label={title} shouldFilter={false} vimBindings={false} loop>
          {children}
        </Command>
      </DialogContent>
    </Dialog>
  );
}

export function CommandInput({ className, ...props }: ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    // 입력칸은 대화상자가 열려 있는 동안 늘 포커스를 갖는 유일한 자리라 따로 포커스 표시를 두지 않는다(캐럿이 보인다).
    <div data-slot="command-input-wrapper" className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
      <Search aria-hidden className="size-4 shrink-0 text-muted-foreground" />
      <CommandPrimitive.Input
        data-slot="command-input"
        className={cn(
          "h-full w-full min-w-0 bg-transparent text-base text-foreground outline-none placeholder:text-muted-foreground",
          className,
        )}
        {...props}
      />
    </div>
  );
}

export function CommandList({ className, ...props }: ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn("max-h-80 scroll-py-1 overflow-x-hidden overflow-y-auto", className)}
      {...props}
    />
  );
}

export function CommandEmpty({ className, ...props }: ComponentProps<typeof CommandPrimitive.Empty>) {
  return (
    <CommandPrimitive.Empty
      data-slot="command-empty"
      className={cn("py-6 text-center text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export function CommandGroup({ className, ...props }: ComponentProps<typeof CommandPrimitive.Group>) {
  return (
    <CommandPrimitive.Group
      data-slot="command-group"
      className={cn(
        "overflow-hidden p-1 text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function CommandItem({ className, ...props }: ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        "relative flex cursor-default items-center gap-2 rounded-md px-2 py-2 text-sm text-foreground outline-none select-none",
        "data-[selected=true]:bg-secondary data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
        // 손가락 포인터 40px 는 admin 전용 CSS 가 프리미티브 표식으로 걸지 않는 손수 만든 행이라 여기서 진다.
        "pointer-coarse:min-h-10",
        "[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

/** 키 이름 하나. 채움 없이 윤곽만 둬 `popover`·`secondary` 어느 면 위에서도 같은 모양이다. */
export function Kbd({ className, ...props }: ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border border-border px-1 font-sans text-xs font-medium text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}
