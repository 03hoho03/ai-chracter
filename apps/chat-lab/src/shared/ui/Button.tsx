import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/shared/lib/cn";

type ButtonVariant = "primary" | "ghost";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

/**
 * 높이 28px 버튼. `primary` 는 화면당 하나뿐인 주 행동, 나머지는 `ghost` 다. `type` 기본값을 `button` 으로 둬 폼 안에서 뜻하지
 * 않게 제출하지 않는다.
 */
export function Button({ variant = "ghost", type = "button", className, ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md text-body whitespace-nowrap",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        "disabled:cursor-default disabled:text-ink-muted motion-safe:transition-colors",
        variant === "primary" && "bg-accent px-3 font-medium text-accent-ink disabled:bg-surface-raised",
        variant === "ghost" && "px-2 text-ink-secondary enabled:hover:bg-surface-raised enabled:hover:text-ink",
        className,
      )}
      {...rest}
    />
  );
}
