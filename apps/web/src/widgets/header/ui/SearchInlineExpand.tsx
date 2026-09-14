import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Input } from "@ai-character-chat/ui/components/input";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useDebounce } from "react-use";

const DEBOUNCE_MS = 300;

/**
 * techspec-global-nav-profile.md §1.2 — 검색 결과 자체는 홈 화면의 일부이므로 별도 라우트 없이
 * 인라인 익스팬드만 구현한다. 홈이 아닌 화면에서 검색을 시작해도 항상 `/`로 이동 + `?q=` 반영.
 *
 * `onExpandedChange`(MR-12) — `sm` 미만에서 펼치면 헤더의 버거·로고를 숨겨야 하는데 그 둘은 `Header`가
 * 그리는 형제 엘리먼트라 이 컴포넌트 내부에서 직접 숨길 수 없다. 펼침 상태 자체(자동 펼침 초기값·디바운스
 * 동기화 등)는 계속 이 컴포넌트가 들고, 값이 바뀔 때마다 `Header`에 알리기만 한다 — 완전히 controlled로
 * 뒤집으면 URL 기반 초기값 계산까지 `Header`로 옮겨야 해서 변경이 더 커진다.
 */
export function SearchInlineExpand({
  onExpandedChange,
}: {
  onExpandedChange?: (expanded: boolean) => void;
} = {}) {
  const navigate = useNavigate();
  const initialQuery = useRouterState({ select: (state) => extractHomeQuery(state.location.search) });
  const [isExpanded, setIsExpanded] = useState(Boolean(initialQuery));
  const [value, setValue] = useState(initialQuery ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  useDebounce(
    () => {
      if (!isExpanded) return;
      const q = value.trim();
      // US-044 — 홈의 정렬/장르/크리에이터/해시태그 필터와 조합 적용되어야 하므로 검색어만 갱신하고
      // 나머지 search param은 보존한다(이전엔 `search: { q }`로 통째로 덮어써 다른 필터가 날아갔다).
      void navigate({ to: "/", search: (prev) => ({ ...prev, q: q === "" ? undefined : q }) });
    },
    DEBOUNCE_MS,
    [value],
  );

  useEffect(() => {
    if (isExpanded) inputRef.current?.focus();
  }, [isExpanded]);

  // 통지 이펙트만 useLayoutEffect다 — `initialQuery`가 있으면 `isExpanded`가 첫 렌더부터 true인데
  // useEffect는 페인트 후에 돌아 첫 프레임에 부모(Header)가 아직 false로 그려져 버거·로고가 한 프레임
  // 노출된다(모바일 폭에서 `?q=` URL 직접 열기 — 2026-09-15 적대적 리뷰가 지목).
  useLayoutEffect(() => {
    onExpandedChange?.(isExpanded);
  }, [isExpanded, onExpandedChange]);

  const collapse = () => {
    setIsExpanded(false);
    setValue("");
  };

  return (
    <div
      className={cn(
        // MR-12 — `sm` 미만 펼침은 더 이상 "선호 폭 `w-40`"이 아니라 헤더 한 줄 전체를 차지한다(`Header`가
        // 이 상태일 때 버거·로고를 숨기고 이 그룹을 3열 모두에 걸치게 한다). `sm` 이상은 현행 `w-64`를
        // 그대로 유지한다 — `min-w-0`은 그 구간에서 아이콘 4개 + 펼친 검색이 좁아질 때의 안전장치로 남는다.
        "flex min-w-0 items-center justify-end motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out",
        isExpanded ? "w-full sm:w-64" : "w-8",
      )}
    >
      {isExpanded ? (
        <div className="flex w-full items-center gap-1">
          <Input
            ref={inputRef}
            name="q"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={() => {
              if (value.trim() === "") collapse();
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") collapse();
            }}
            placeholder="캐릭터·스토리 검색"
            aria-label="캐릭터·스토리 검색"
            // 옆 Button(size="icon")이 36px라 Input 기본값(D-4로 h-9=36px)과 이미 맞는다 — 오버라이드 제거.
            className="min-w-0"
          />
          {/* MR-12 — `sm` 미만 독점 상태는 닫기가 좌측이다(모바일 검색의 통상 배치: 뒤로/닫기 좌측 +
              입력칸). `sm` 이상은 현행대로 입력칸 뒤(우측)에 둔다. DOM 순서(Input 다음 닫기)는 그대로
              두고 `max-sm:order-first`로 시각 순서만 뒤집는다 — JS 분기 없이 `sm:` 클래스로 가른다. */}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="검색 닫기"
            onClick={collapse}
            className="max-sm:order-first"
          >
            <X aria-hidden />
          </Button>
        </div>
      ) : (
        <Button type="button" variant="ghost" size="icon" aria-label="검색" onClick={() => setIsExpanded(true)}>
          <Search aria-hidden />
        </Button>
      )}
    </div>
  );
}

function extractHomeQuery(search: unknown): string | undefined {
  if (search && typeof search === "object" && "q" in search) {
    const { q } = search;
    return typeof q === "string" ? q : undefined;
  }
  return undefined;
}
