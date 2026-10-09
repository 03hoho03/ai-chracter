import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useId } from "react";

import { WebnovelCover, type HomeWebnovelItem } from "@/entities/webnovel";
import { useHorizontalScrollClip } from "@/shared/lib/scroll/useHorizontalScrollClip";

/** 홈 노벨 섹션 — 운영자가 고른 노벨을 가로 한 줄로(넘치면 가로 스크롤, 스크롤바 숨김 — 좁은 화면에서는 화면 끝까지
 * 이어진다). 캐릭터·스토리 두 홈에 같은 섹션이고 큐레이션 섹션 바로 아래·결과 그리드 위에 놓인다. 항목은 2:3 표지 ·
 * 제목 두 줄 · 원작 한 줄이고 지표는 넣지 않는다(홈의 밝기·밀도 예산). 잘린 쪽은 끝을 배경색으로 흐려 더 있다는 것을
 * 알린다(오버레이 스크롤바는 그 신호가 없다). */
export function HomeWebnovelSection({ items }: { items: readonly HomeWebnovelItem[] }) {
  const headingId = useId();
  const scroll = useHorizontalScrollClip();

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 id={headingId} className="text-sm font-medium text-muted-foreground">
          노벨 · 대화로 만든 소설
        </h2>
        <Link
          to="/webnovels"
          className="inline-flex items-center gap-0.5 rounded-sm text-sm text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          더 보기
          <ChevronRight aria-hidden className="size-4" />
        </Link>
      </div>
      <div className="relative -mx-4 sm:mx-0">
        <div ref={scroll.ref} className="overflow-x-auto px-4 py-1 [scrollbar-width:none] sm:px-0 [&::-webkit-scrollbar]:hidden">
          <ul className="flex w-max gap-3">
            {items.map((item) => (
              <li key={item.id} className="w-28 shrink-0 sm:w-36">
                <Link
                  to="/webnovels/$novelId"
                  params={{ novelId: item.id }}
                  className="flex flex-col gap-2 rounded-xl focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"
                >
                  <WebnovelCover url={item.source.coverUrl} className="w-full" />
                  <span className="flex flex-col gap-0.5">
                    <span className="line-clamp-2 text-sm font-medium break-keep text-foreground">{item.title}</span>
                    <span className="line-clamp-1 text-xs break-keep text-muted-foreground">원작 · {item.source.title}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
        {scroll.isClippedLeft && (
          <div aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-linear-to-r from-background" />
        )}
        {scroll.isClippedRight && (
          <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-linear-to-l from-background" />
        )}
      </div>
    </section>
  );
}
