import type { ManuscriptTocEntry } from "../model/parseManuscript";

type GuideTocProps = {
  entries: ManuscriptTocEntry[];
};

/**
 * 원고 절 목차. 페이지 안(`<main>`)의 한 블록이지 사이드 레일이 아니다 — 크롬은 전역 헤더 하나뿐이다.
 * 앵커 id 는 원고의 `{#id}` 이고 단계 절이면 빌더 탭 id 와 같아서, 빌더의 탭에서 해당 절로 바로 거는
 * 링크를 나중에 코드 변경 없이 붙일 수 있다.
 *
 * 항목은 행 전체가 눌리는 링크다(좁은 화면에서 한 손으로 누르기 쉽게 높이 36px). 포커스는 저장소의
 * 카드 링크와 같은 레시피로, 불투명 1px 보더가 3:1 을 지고 반투명 링이 두께를 더한다.
 */
export function GuideToc({ entries }: GuideTocProps) {
  return (
    <nav aria-labelledby="guide-toc-title" className="flex flex-col gap-2 rounded-xl border border-border p-4">
      <h2 id="guide-toc-title" className="text-sm font-semibold text-foreground">
        목차
      </h2>
      <ol className="-mx-2 flex flex-col">
        {entries.map((entry) => (
          <li key={entry.id}>
            <a
              href={`#${entry.id}`}
              className="flex min-h-9 items-center break-keep rounded-md border border-transparent px-2 py-1.5 text-sm text-muted-foreground outline-none motion-safe:transition-colors hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {entry.text}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
