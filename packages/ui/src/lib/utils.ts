import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// tailwind-merge는 기본 스케일(`text-xs` 등)과 임의값(`text-[11px]`)은 font-size로
// 알아보지만, `@theme`의 커스텀 토큰 이름(`text-badge` 등)은 스캐너가 모르는 클래스라
// 기본적으로 text-color 그룹으로 오분류한다. 그 상태로 cn()에서 색 클래스(예:
// `text-muted-foreground`)와 합쳐지면 "같은 축(색)"으로 오인해 먼저 온 쪽을 조용히
// 탈락시킨다 — 실제로 `/my` 카드 배지 52개가 이 경로로 11px→16px이 됐다(2026-09
// 실측). 아래에서 `text-badge`를 font-size 그룹으로 명시 등록해 바로잡는다.
//
// 새 `--text-*` 토큰을 globals.css의 `@theme`에 추가하면 여기에도 등록해야 한다.
// 안 하면 같은 방식으로 색 클래스와 합쳐질 때 조용히 사라진다.
//
// `max-h-dialog`(globals.css의 `@utility`)도 같은 이유로 max-h 그룹에 등록한다. 등록이 없으면
// 기본값 `has-data-[slot=dialog-body]:max-h-dialog`(dialog.tsx)와 호출부의 같은 변형
// `has-data-[slot=dialog-body]:max-h-[85vh]`를 서로 다른 축으로 보고 둘 다 남기는데, 특이도가 같아
// CSS 생성 순서가 승자를 정하고 그 순서에서는 호출부 값이 조용히 진다. 등록하면 뒤에 온 호출부 값만
// 남는다.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: { "font-size": ["text-badge"], "max-h": ["max-h-dialog"] },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
