import type { ReactNode } from "react";

/**
 * 화면 폭·거터의 단일 소스. 목록·상세 모두 이것 하나를 쓰고, 상세의 본문·조치 열 폭은 `DetailLayout` 이 나눈다.
 * 지금은 셸 본문 래퍼가 `<main>` 이 아니라서 이것이 `<main>` 을 그린다 — 아직 옮기지 않은 화면은 각자 자기
 * `<main>` 을 가진다.
 */
export function PageContainer({ children }: { children: ReactNode }) {
  return <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-10">{children}</main>;
}
