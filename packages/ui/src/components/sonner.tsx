import type { CSSProperties } from "react"
import { Toaster as Sonner, type ToasterProps } from "sonner"
import {
  CircleCheckIcon,
  InfoIcon,
  TriangleAlertIcon,
  OctagonXIcon,
  Loader2Icon,
} from "lucide-react"

import { cn } from "@ai-character-chat/ui/lib/utils"

const Toaster = ({ theme = "light", toastOptions, ...props }: ToasterProps) => {
  return (
    <Sonner
      theme={theme}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
        } as CSSProperties
      }
      toastOptions={{
        ...toastOptions,
        classNames: {
          ...toastOptions?.classNames,
          // sonner 가 주입하는 CSS 는 Tailwind 레이어 밖이라 토스터 상자의 시스템 서체 지정을 유틸리티로
          // 덮을 수 없다. 그 규칙이 걸리지 않는 토스트 항목에 직접 서체를 준다. 줄바꿈은 sonner 가
          // 긴 낱말을 끊는 규칙만 두고 어절 규칙이 없어 한국어가 어절 중간에서 끊기므로 여기서 더한다.
          toast: cn("font-sans break-keep", toastOptions?.classNames?.toast),
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
