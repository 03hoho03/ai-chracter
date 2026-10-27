import { useId } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Link } from "@tanstack/react-router";
import { useAtom } from "jotai";

import { useCloverPricingQuery } from "@/entities/clover";
import { contentDetailModalAtom } from "@/entities/content";
import { useSessionQuery } from "@/entities/session";
import { toPublisherName, useDerivedWebnovelsQuery } from "@/entities/webnovel";

import { isDerivedNovelsRequestable, toDerivedNovelsArea } from "../model/derivedNovelsArea";

type DerivedNovelsSectionProps = {
  contentId: string;
  isOwner: boolean;
  derivedNovelsVisible: boolean;
};

/** 원작 상세의 "이 작품으로 만든 소설" — 지금 읽을 수 있는 노벨을 원작자 공식과 파생을 한 목록에 서버 순서(최근 공개순)
 * 그대로 놓고, 항목마다 어느 쪽인지 적는다.
 *
 * 표지를 그리지 않는다: 노벨 표지는 원작 썸네일이라 항목마다 바로 위 대표 그림과 같은 그림이 된다. 모달(`popover` 표면)과
 * 페이지(`background`)가 같은 본문을 쓰므로 행 hover 는 두 표면 모두에서 보이는 `secondary` 다.
 *
 * 응답 전·실패·빈 목록이면 아무것도 그리지 않는다 — 공개 페이지라 이 목록의 실패가 원작 상세를 깨뜨리면 안 되고, 비어 있는
 * 영역은 알릴 것이 없다. */
export function DerivedNovelsSection({ contentId, isOwner, derivedNovelsVisible }: DerivedNovelsSectionProps) {
  const headingId = useId();
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);
  const session = useSessionQuery().data;
  const pricing = useCloverPricingQuery().data;
  const isRequestable = isDerivedNovelsRequestable({
    isLoggedIn: session !== undefined,
    pricingEnabled: pricing?.novelPublicEnabled,
    sessionEnabled: session?.novelPublicEnabled,
  });
  const query = useDerivedWebnovelsQuery(contentId, { enabled: isRequestable });
  const area = toDerivedNovelsArea({
    // 닫힌 동안(로그아웃 직후 등)에 남은 캐시를 그리지 않는다.
    pages: isRequestable ? query.data?.pages : undefined,
    isOwner,
    derivedNovelsVisible,
  });

  if (area.kind === "none") return null;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h2 id={headingId} className="text-sm font-semibold text-foreground">
        이 작품으로 만든 소설
      </h2>
      {area.isHiddenFromOthers && (
        <p className="text-xs break-keep text-muted-foreground">다른 회원에게는 숨겨 둔 목록이에요.</p>
      )}
      <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-lg border border-border">
        {area.items.map((item) => {
          const meta = [toPublisherName(item), `${item.chapterCount}화`].filter((part) => part !== null);
          return (
            <li key={item.id}>
              {/* 행 전체가 노벨 작품 정보로 가는 링크 하나다. 포커스는 둥근 목록 안쪽에 그린다(`overflow-hidden` 이 바깥
                  링을 자른다). 라이트 `muted-foreground` 는 `secondary` 위에서 AA 미달이라 hover 때 글자도 올린다.
                  모달에서 누르면 모달을 닫고, `open()` 이 밀어 넣은 `/content/...` 기록을 덮어써 노벨에서 뒤로가기가
                  풀페이지 상세로 튀지 않게 한다("내 대화 목록" 링크와 같은 처방). */}
              <Link
                to="/webnovels/$novelId"
                params={{ novelId: item.id }}
                replace={modalState !== undefined}
                onClick={(event) => {
                  // 수정키 클릭은 새 탭·새 창으로 열고 이 탭은 그대로 둔다 — 모달까지 닫으면 주소는 상세에 남은 채
                  // 화면만 목록으로 돌아간다.
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
                  setModalState(undefined);
                }}
                className="group flex flex-col gap-0.5 px-3 py-2.5 motion-safe:transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:inset-ring-2 focus-visible:inset-ring-ring"
              >
                <span className="flex items-start gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">{item.title}</span>
                  {/* 출처 표기라 중립 상태 배지 — 색 없이 윤곽과 글자로만. */}
                  <span className="inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium whitespace-nowrap text-muted-foreground group-hover:text-foreground">
                    {item.source.unofficial ? "파생" : "원작자 공식"}
                  </span>
                </span>
                <span className="truncate text-xs text-muted-foreground tabular-nums group-hover:text-foreground">
                  {meta.join(" · ")}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {query.hasNextPage && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={query.isFetchingNextPage}
          onClick={() => {
            if (query.isFetchingNextPage) return;
            void query.fetchNextPage();
          }}
          className="self-center text-muted-foreground hover:bg-secondary aria-disabled:opacity-65 pointer-coarse:h-10"
        >
          더 보기
        </Button>
      )}
    </section>
  );
}
