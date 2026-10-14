import { useId } from "react";
import { ChevronRight } from "lucide-react";

import type { PublishIssueRow } from "../model/publishIssues";

type PublishIssueListProps = {
  rows: readonly PublishIssueRow[];
  /** 줄을 눌렀을 때 — 그 칸으로 간다(탭 전환·항목 펼치기·포커스는 셸의 첫 오류 이동 경로). */
  onSelect: (path: string) => void;
};

/**
 * 발행이 막혔을 때 폼 열 맨 위에 서는 "발행 전에 확인할 항목" 목록. 두 빌더가 함께 쓴다.
 *
 * 줄마다 버튼이라 키보드로 훑고 Enter 로 그 칸에 간다. 고친 줄은 셸이 오류를 갈아 끼우는 즉시 빠지고, 다 빠지면 목록 자체가 문구 없이
 * 사라진다(셸이 그리지 않는다). 제목은 `aria-live` 라 줄 수가 바뀌면 새 개수를 읽힌다 — 처음 나타날 때는 읽히지 않지만 그때는 발행
 * 토스트가 이 목록을 가리킨다.
 *
 * 모양은 오류 배너다 — `bg-destructive/10` 틴트에 `text-destructive-text` 제목, 테두리 없음(DESIGN.md Colors 절 Semantic). 줄 글자는
 * 틴트 위에서도 읽히게 `foreground` 이고 빨강은 제목 한 줄에만 둔다. 고정·sticky 가 아니라 문서 흐름 안에 둔다 — 늘 떠 있는 크롬은
 * 헤더 한 줄뿐이다.
 */
export function PublishIssueList({ rows, onSelect }: PublishIssueListProps) {
  const titleId = useId();

  return (
    <section aria-labelledby={titleId} className="rounded-lg bg-destructive/10 px-4 py-3">
      <h2 id={titleId} aria-live="polite" aria-atomic="true" className="text-sm font-medium text-destructive-text">
        발행 전에 확인할 항목 {rows.length}개
      </h2>
      <ul className="-mx-2 mt-2 flex flex-col">
        {rows.map((row) => (
          <li key={row.path}>
            <button
              type="button"
              onClick={() => onSelect(row.path)}
              className="flex min-h-9 w-full items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left text-sm outline-none hover:bg-destructive/10 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
            >
              <span className="min-w-0 flex-1 break-keep wrap-break-word">{row.label}</span>
              <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
