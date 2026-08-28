import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Input } from "@ai-character-chat/ui/components/input";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useDebounce } from "react-use";

const DEBOUNCE_MS = 300;

function extractHomeQuery(search: unknown): string | undefined {
  if (search && typeof search === "object" && "q" in search) {
    const { q } = search;
    return typeof q === "string" ? q : undefined;
  }
  return undefined;
}

/**
 * techspec-global-nav-profile.md §1.2 — 검색 결과 자체는 홈 화면의 일부이므로 별도 라우트 없이
 * 인라인 익스팬드만 구현한다. 홈이 아닌 화면에서 검색을 시작해도 항상 `/`로 이동 + `?q=` 반영.
 */
export function SearchInlineExpand() {
  const navigate = useNavigate();
  const initialQuery = useRouterState({ select: (state) => extractHomeQuery(state.location.search) });
  const [expanded, setExpanded] = useState(Boolean(initialQuery));
  const [value, setValue] = useState(initialQuery ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  useDebounce(
    () => {
      if (!expanded) return;
      const q = value.trim();
      // US-044 — 홈의 정렬/장르/크리에이터/해시태그 필터와 조합 적용되어야 하므로 검색어만 갱신하고
      // 나머지 search param은 보존한다(이전엔 `search: { q }`로 통째로 덮어써 다른 필터가 날아갔다).
      void navigate({ to: "/", search: (prev) => ({ ...prev, q: q === "" ? undefined : q }) });
    },
    DEBOUNCE_MS,
    [value],
  );

  useEffect(() => {
    if (expanded) inputRef.current?.focus();
  }, [expanded]);

  const collapse = () => {
    setExpanded(false);
    setValue("");
  };

  return (
    <div
      className={cn(
        // `w-40`은 선호 폭이지 하한이 아니다 — `min-w-0`이 없으면 390px 폭에서 헤더 아이콘 4개 + 펼친 검색이
        // 합쳐 뷰포트를 14px 넘겨 페이지가 가로로 스크롤된다. 좁을 때만 줄어들고 여유가 있으면 w-40/sm:w-64를 지킨다.
        "flex min-w-0 items-center justify-end motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out",
        expanded ? "w-40 sm:w-64" : "w-8",
      )}
    >
      {expanded ? (
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
            className="h-8 min-w-0"
          />
          <Button type="button" variant="ghost" size="icon" aria-label="검색 닫기" onClick={collapse}>
            <X aria-hidden />
          </Button>
        </div>
      ) : (
        <Button type="button" variant="ghost" size="icon" aria-label="검색" onClick={() => setExpanded(true)}>
          <Search aria-hidden />
        </Button>
      )}
    </div>
  );
}
