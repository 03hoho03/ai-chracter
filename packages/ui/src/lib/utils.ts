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
const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": ["text-badge"] } },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
