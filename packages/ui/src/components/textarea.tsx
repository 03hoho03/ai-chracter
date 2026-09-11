import * as React from "react"

import { cn } from "@ai-character-chat/ui/lib/utils"

/** `disabled:bg-input/50`은 죽은 경로가 아니다 — 채팅 입력창(`ChatRoomView`)과 빌더 미리보기
 * (`PreviewSessionView`)가 전송 중 내내 `disabled`로 렌더한다. `Input` 쪽은 0건이다.
 *
 * `--input`을 0.89→0.62(라이트)로 옮긴 뒤 이 자리를 실측했다(2026-08-29). `disabled:opacity-50`이
 * 함께 걸려 채움의 실효 알파는 **0.25**다. 결과는 **개선**이었다 — 이전 값에서는 보더가 흰 배경에
 * 사실상 소멸해(237/255) disabled가 거의 안 보였는데, 지금은 확실히 죽은 상자로 읽힌다
 * (채움:표면 1.0807 → 1.3077 라이트 / 1.0643 → 1.2521 다크).
 *
 * 규정 위반은 아니다(1.4.11·1.4.3이 비활성 컴포넌트·텍스트를 명시적으로 면제한다). 다만 두 가지를
 * 남겨 둔다: (1) 다크의 disabled 채움 sRGB 36은 `secondary`와 픽셀 동일이라 "비활성 입력창"과
 * "활성 상태 컨트롤"이 같은 회색을 쓴다 (2) placeholder 가독성이 1.90→1.57(라이트)로 내려갔다.
 * 둘 다 면제 범위 안이지만 방향은 나빠졌으므로, 이 값을 또 옮길 땐 여기부터 볼 것. */

/** `px-3` — 버튼과 같은 좌우 패딩 계보로 맞춘다(design-system-goal-prompt.md D-4). `py-2`는 그대로
 * 둔다 — Textarea는 여러 줄이라 세로 패딩이 실제로 의미가 있다(단일 행 컨트롤인 Input/Button과는
 * 계보가 다르다). 높이는 `min-h-16` + `field-sizing-content`가 정하므로 건드리지 않는다. */

/** `text-base`(16px) 고정 — `md:text-sm`을 지운 것도 이 이유다. 16px 미만 입력에 포커스하면
 * iOS Safari가 자동으로 확대한다(표준 관용구). `--text-sm`이 16px가 된 뒤로는 그 오버라이드가
 * 아무 효과 없는 죽은 코드였다(design-system-goal-prompt.md D-5/D-8). */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-lg border border-input bg-transparent px-3 py-2 text-base motion-safe:transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
