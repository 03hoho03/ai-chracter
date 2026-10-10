import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Input } from "@ai-character-chat/ui/components/input";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useDebounce } from "react-use";

import { CONTENT_TYPE_LABEL, resolveHomeContentType } from "@/entities/content";

import { resolveSearchInputSync } from "../model/searchInputSync";

const DEBOUNCE_MS = 300;

/**
 * 검색 결과 자체는 홈 화면의 일부이므로 별도 라우트 없이
 * 인라인 익스팬드만 구현한다. 홈이 아닌 화면에서 검색을 시작해도 항상 `/`로 이동 + `?q=` 반영.
 *
 * **닫기·Esc는 입력칸을 접기만 하고 검색어는 지우지 않는다.** 걸린 검색어는 홈의 칩 줄이 `“검색어” ×` 칩으로
 * 보여 주고 해제도 그 칩이 맡는다 — 닫기가 검색어를 지우는 방식은 브라우저 뒤로/앞으로로 `?q=`가 되살아날 때
 * 입력칸은 접힌 채 검색어만 남아 화면에 안 보이는 필터가 생긴다(칩은 URL에서 그려지므로 그런 상태가 없다).
 *
 * `onExpandedChange` — `sm` 미만에서 펼치면 헤더의 버거·로고를 숨겨야 하는데 그 둘은 `Header`가
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
  // 홈이 아니면 `undefined`다. 검색어(`q`)는 홈 스키마에만 있으므로 홈 밖에는 걸린 검색어가 없다.
  const homeSearch = useSearch({ from: "/", shouldThrow: false });
  const urlQuery = homeSearch?.q;
  const [isExpanded, setIsExpanded] = useState(Boolean(urlQuery));
  const [value, setValue] = useState(urlQuery ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  const expandedGroupRef = useRef<HTMLDivElement>(null);
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  // 접히는 순간 포커스가 펼친 입력칸 쪽(입력칸·닫기 버튼)에 있었는가. 그 둘이 사라지면 포커스가 `<body>` 로
  // 떨어지므로, 그랬다면 접힌 뒤 다시 생기는 검색 버튼으로 돌려준다(아래 효과).
  const shouldFocusSearchButtonRef = useRef(false);
  // 디바운스가 URL에 마지막으로 쓴 검색어. URL 검색어가 이것과 다르면 바깥에서 바뀐 것이다(아래 동기화 효과).
  const lastWrittenQueryRef = useRef(urlQuery);
  // 검색 범위는 지금 보고 있는 홈의 유형이다. 홈 밖에서 검색하면 파라미터 없는 `/`(스토리)로 간다.
  const searchLabel = `${CONTENT_TYPE_LABEL[resolveHomeContentType(homeSearch?.type)]} 검색`;

  useDebounce(
    () => {
      if (!isExpanded) return;
      const q = value.trim();
      // 홈에서는 유형/정렬/장르/크리에이터/해시태그 필터와 조합 적용되어야 하므로 검색어만 갱신하고
      // 나머지 search param은 보존한다(이전엔 `search: { q }`로 통째로 덮어써 다른 필터가 날아갔다).
      // 홈 밖에서는 지금 화면의 search를 펼치지 않는다 — 즐겨찾기·프로필·내 작품의 `?type=`이 홈 유형으로
      // 새어 들어간다.
      const next = q === "" ? undefined : q;
      lastWrittenQueryRef.current = next;
      void navigate({ to: "/", search: homeSearch ? { ...homeSearch, q: next } : { q: next } });
    },
    DEBOUNCE_MS,
    [value],
  );

  useEffect(() => {
    if (isExpanded) {
      inputRef.current?.focus();
      return;
    }
    if (shouldFocusSearchButtonRef.current) {
      shouldFocusSearchButtonRef.current = false;
      searchButtonRef.current?.focus();
    }
  }, [isExpanded]);

  // 사용자 이벤트로 인한 펼침/접힘은 `setIsExpanded`를 직접 부르는 지점
  // (검색 버튼 onClick·`collapse`)에서 `onExpandedChange`도 함께 부른다. 여기 남는 이펙트는 더 이상
  // "상태 복제"가 아니라 "URL 파생 초기값을 부모에 한 번 알리는 핸드셰이크"다 — `isExpanded`의 초기값이
  // `useState(Boolean(urlQuery))`로 URL에서 오는 그 한 경우만 사용자 이벤트가 아니라서, deps를 `[]`로
  // 좁혀 마운트 1회만 알린다. useEffect가 아니라 useLayoutEffect인 이유는 그대로다 — URL 검색어가
  // 있으면 `isExpanded`가 첫 렌더부터 true인데 useEffect는 페인트 후에 돌아 첫 프레임에 부모(Header)가
  // 아직 false로 그려져 버거·로고가 한 프레임 노출된다(모바일 폭에서 `?q=` URL 직접 열기 — 2026-09-15
  // 적대적 리뷰가 지목).
  useLayoutEffect(() => {
    onExpandedChange?.(isExpanded);
  }, []);

  // 닫기 버튼·Esc·URL 검색어가 지워져 접힐 때는 포커스가 펼친 쪽에 있어 검색 버튼으로 돌려준다. 빈 입력칸에서
  // 포커스가 바깥으로 떠나 접힐 때(blur)와 로고처럼 바깥을 눌러 접힐 때는 포커스가 이미 다른 곳이라 건드리지 않는다.
  const collapse = () => {
    // 참일 때만 세운다 — 같은 접힘에서 사라지는 입력칸의 blur 가 한 번 더 부르면 그때는 포커스가 이미 `<body>` 다.
    if (expandedGroupRef.current?.contains(document.activeElement)) shouldFocusSearchButtonRef.current = true;
    setIsExpanded(false);
    setValue("");
    onExpandedChange?.(false);
  };

  // URL 검색어가 바깥에서 바뀌면(로고·유형 전환·해시태그·칩 ×·`필터 지우기`·뒤로/앞으로) 펼친 입력칸이 옛
  // 검색어로 남아 칩과 다른 말을 한다 — 지워졌으면 접고, 다른 값이 됐으면 그 값으로 채운다. 자기 쓰기와
  // 바깥 변경은 디바운스가 마지막으로 쓴 값으로 가른다(규칙은 `resolveSearchInputSync`). deps를 URL 검색어
  // 하나로 둬 타이핑으로는 이 효과가 돌지 않는다.
  useEffect(() => {
    const sync = resolveSearchInputSync({
      urlQuery,
      lastWrittenQuery: lastWrittenQueryRef.current,
      inputValue: value,
      isExpanded,
    });
    lastWrittenQueryRef.current = urlQuery;
    if (sync.kind === "collapse") collapse();
    if (sync.kind === "fill") setValue(sync.value);
  }, [urlQuery]);

  return (
    <div
      className={cn(
        // `sm` 미만 펼침은 더 이상 "선호 폭 `w-40`"이 아니라 헤더 한 줄 전체를 차지한다(`Header`가
        // 이 상태일 때 버거·로고를 숨기고 이 그룹을 3열 모두에 걸치게 한다). `sm` 이상은 `w-64`다 — `min-w-0`은
        // 그 폭이 모자랄 때(`lg` 미만 헤더의 좁은 3열, `lg` 이상에서 아이콘 넷과 함께 놓일 때) 검색만 줄어들게 하는 안전장치다.
        "flex min-w-0 items-center justify-end motion-safe:transition-[width] motion-safe:duration-200 motion-safe:ease-out",
        isExpanded ? "w-full sm:w-64" : "w-8",
      )}
    >
      {isExpanded ? (
        <div ref={expandedGroupRef} className="flex w-full items-center gap-1">
          <Input
            ref={inputRef}
            name="q"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onBlur={(event) => {
              if (value.trim() !== "") return;
              // 빈 입력칸에서 Tab 으로 옆 닫기 버튼에 가면 그 버튼도 함께 접혀 사라진다 — 검색 버튼이 받는다.
              if (expandedGroupRef.current?.contains(event.relatedTarget)) shouldFocusSearchButtonRef.current = true;
              collapse();
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") collapse();
            }}
            placeholder={searchLabel}
            aria-label={searchLabel}
            // 옆 Button(size="icon")이 36px라 Input 기본값(h-9=36px)과 이미 맞는다 — 오버라이드 제거.
            className="min-w-0"
          />
          {/* `sm` 미만 독점 상태는 닫기가 좌측이다(모바일 검색의 통상 배치: 뒤로/닫기 좌측 +
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
        <Button
          ref={searchButtonRef}
          type="button"
          variant="ghost"
          size="icon"
          aria-label="검색"
          onClick={() => {
            // 걸린 검색어가 있으면 그 말로 채워 연다 — 칩과 입력칸이 다른 말을 하지 않게.
            setValue(urlQuery ?? "");
            setIsExpanded(true);
            onExpandedChange?.(true);
          }}
        >
          <Search aria-hidden />
        </Button>
      )}
    </div>
  );
}
