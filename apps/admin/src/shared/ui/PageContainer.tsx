import type { ReactNode } from "react";

/**
 * 화면 폭·거터의 단일 소스. 셸 밖 로그인 화면을 뺀 모든 화면이 이것 하나를 쓰고, 상세의 본문·조치 열 폭은
 * `DetailLayout` 이 나눈다. `<main>` 랜드마크는 셸의 본문 래퍼가 가지므로 여기는 div 다.
 */
export function PageContainer({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-10">{children}</div>;
}
