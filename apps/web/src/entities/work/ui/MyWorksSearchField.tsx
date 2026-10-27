import { useEffect, useRef, useState, type RefObject } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Input } from "@ai-character-chat/ui/components/input";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Search, X } from "lucide-react";
import { useDebounce } from "react-use";

import { normalizeMyWorksQuery } from "../model/workQuery";

/** 헤더의 홈 검색과 같은 값 — 타이핑을 멈춘 뒤 이만큼 지나야 URL(과 그에 묶인 목록 요청)이 바뀐다. */
const DEBOUNCE_MS = 300;

type MyWorksSearchFieldProps = {
  inputRef: RefObject<HTMLInputElement | null>;
  /** URL에 걸린(정규화된) 검색어. */
  query: string | undefined;
  onQueryChange: (query: string | undefined) => void;
  className?: string;
};

/**
 * 내 작품 제목 검색 칸 — 내 작품 화면과 스튜디오가 함께 쓴다. 제출 버튼 없이 입력을 멈추면 걸리는 방식이 헤더의 홈 검색(`SearchInlineExpand`)과 같다 —
 * 한 앱에서 검색 칸 둘이 서로 다르게 동작하면 사용자가 어느 쪽이 Enter를 기다리는지 따져야 한다.
 *
 * 입력칸 값은 로컬 state이고 URL에는 디바운스 뒤에 정규화된 값만 쓴다. 칸이 101자를 들고 있어도 URL과 요청은
 * 100자다(서버 상한 — `normalizeMyWorksQuery`).
 */
export function MyWorksSearchField({ inputRef, query, onQueryChange, className }: MyWorksSearchFieldProps) {
  const [value, setValue] = useState(query ?? "");
  // 디바운스가 마지막으로 URL에 쓴 검색어. URL 검색어가 이것과 다르면 바깥에서 바뀐 것이다(아래 동기화 효과).
  const lastWrittenQueryRef = useRef(query);

  useDebounce(
    () => {
      const next = normalizeMyWorksQuery(value);
      // 마운트 직후와 공백만 더 친 경우처럼 보낼 값이 그대로면 쓰지 않는다 — 같은 주소로 내비게이션하면
      // 뒤로가기 기록만 한 칸 늘어난다.
      if (next === query) return;
      lastWrittenQueryRef.current = next;
      onQueryChange(next);
    },
    DEBOUNCE_MS,
    [value],
  );

  // 빈 상태의 `검색어 지우기`·`필터 모두 해제`, 뒤로/앞으로가 URL 검색어를 바꾸면 칸이 옛 말을 들고 남는다 —
  // 그 값으로 맞춘다. 자기 쓰기가 커밋된 것은 건드리지 않는다(디바운스가 발사된 뒤 커밋 전에 친 글자를 지우게 된다).
  // deps를 URL 검색어 하나로 둬 타이핑으로는 돌지 않는다.
  useEffect(() => {
    if (query !== lastWrittenQueryRef.current) setValue(query ?? "");
    lastWrittenQueryRef.current = query;
  }, [query]);

  // 지우기는 기다릴 이유가 없다 — 디바운스를 거치지 않고 바로 URL에서 뺀다.
  const handleClear = () => {
    setValue("");
    inputRef.current?.focus();
    if (query === undefined) return;
    lastWrittenQueryRef.current = undefined;
    onQueryChange(undefined);
  };

  return (
    <div className={cn("relative", className)}>
      <Search
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        ref={inputRef}
        type="search"
        name="q"
        enterKeyHint="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="제목으로 찾기"
        aria-label="내 작품 제목 검색"
        // 같은 줄의 칩·`공개 여부` 트리거(`size="sm"`)와 높이를 맞춘다. 글자는 프리미티브의 16px 그대로다(iOS 확대 방지).
        // 브라우저 기본 지우기 단추는 숨긴다 — 크롬은 다크에서도 그것을 순백(#fff)으로 그려 이 테마의 밝기 천장
        // (`foreground`)을 넘는다. 대신 아래 `검색어 지우기` 단추가 그 자리를 맡는다.
        className="h-8 pr-8 pl-8 [&::-webkit-search-cancel-button]:appearance-none"
      />
      {value !== "" && (
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="검색어 지우기"
          onClick={handleClear}
          className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        >
          <X aria-hidden />
        </Button>
      )}
    </div>
  );
}
