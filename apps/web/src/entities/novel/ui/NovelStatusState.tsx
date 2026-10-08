import type { ReactNode } from "react";

/** 소설을 못 보여 줄 때(없음·불러오기 실패·화 없음)의 화면 한가운데 안내. 그 상태가 페이지의 전부라 제목은 `h1`
 * 이다. 모양은 `NovelizeLockedState` 와 같다. */
export function NovelStatusState({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center break-keep">
      {icon}
      <h1 className="text-lg font-semibold text-foreground">{title}</h1>
      {children}
    </div>
  );
}
