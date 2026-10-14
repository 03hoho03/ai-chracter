import { useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown } from "lucide-react";

type CollapsibleDescriptionProps = {
  /** 설명 원문. 바뀌면 다시 잰다 — 정확히 네 줄이던 글이 늘면 자는 이미 네 줄 높이라 크기 감시로는 모른다. */
  text: string;
  children: ReactNode;
};

/**
 * 상세 설명이 네 줄을 넘으면 세 줄로 접고 "더 보기"를 둔다. 네 줄까지는 그대로 다 보인다 — 한 줄을 감추려고 버튼 한 줄을
 * 쓰는 것은 아무것도 줄이지 않는다.
 *
 * 글 속 그림 태그가 있으면 설명이 문단·그림 블록 여럿이라 `line-clamp` 가 듣지 않는다. 그래서 줄높이 배수(`lh`)의 최대
 * 높이로 자른다. 상자 둘이 각자 한 가지를 맡는다: 안쪽은 네 줄 높이에서 잘라 "네 줄을 넘는가"를 재는 자(넘지 않으면 아무것도
 * 가리지 않는다), 바깥은 넘을 때만 세 줄로 접어 보이는 높이를 정한다. 줄높이를 숫자로 읽어 계산하지 않아도 된다.
 *
 * 잘렸는지는 그린 뒤 높이로 재되 칠하기 전(레이아웃 효과)에 정해 버튼이 나타났다 사라지는 깜빡임이 없다. 잘림은 화면에서만이라
 * 스크린리더는 접힌 상태에서도 설명 전체를 읽는다. 높이 전환 애니메이션은 두지 않는다 — 접힌 높이에서 내용 높이로 가는 전환은
 * 내용 높이를 따로 재야 하고, 어두운 방에서 긴 글이 미끄러져 펼쳐질 이유도 없다.
 */
export function CollapsibleDescription({ text, children }: CollapsibleDescriptionProps) {
  const contentId = useId();
  const rulerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [isCollapsible, setIsCollapsible] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  // 펼친 동안은 재지 않는다 — 잘림이 풀려 "안 넘침"으로 읽히면 "접기" 버튼이 사라진다. 크기가 바뀌면(창 크기·모달 폭,
  // 늦게 도착한 그림) 다시 재고, 글꼴이 늦게 들어와 줄바꿈이 달라지는 경우도 잡는다(잘린 상자는 높이가 그대로라 크기
  // 감시로는 모른다).
  useLayoutEffect(() => {
    const ruler = rulerRef.current;
    if (isExpanded || !ruler) return;
    // 포커스를 가진 버튼은 안 넘치게 됐어도 남긴다. 펼친 채 화면을 넓혀 접으면 그 자리에서 넘침이 없어질 수 있는데, 그때
    // 버튼을 내리면 키보드·스크린리더 포커스가 문서 맨 앞(body)으로 튕긴다. 남은 버튼은 다음 재기에서 내린다.
    const measure = () => {
      const isOverflowing = ruler.scrollHeight > ruler.clientHeight;
      const isButtonFocused = buttonRef.current !== null && buttonRef.current === document.activeElement;
      setIsCollapsible(isOverflowing || isButtonFocused);
    };
    measure();
    // 폭·높이가 둘 다 그대로인 알림은 건너뛴다 — 감시를 걸면 바로 오는 첫 알림이 그렇다. 폭만 보면 안 된다: 그림이 늦게
    // 도착하면 폭은 그대로여도 내용이 자란다(자는 네 줄에서 잘리므로 그때는 자의 높이가 자란다).
    let measuredWidth = ruler.clientWidth;
    let measuredHeight = ruler.clientHeight;
    const observer = new ResizeObserver(() => {
      if (ruler.clientWidth === measuredWidth && ruler.clientHeight === measuredHeight) return;
      measuredWidth = ruler.clientWidth;
      measuredHeight = ruler.clientHeight;
      measure();
    });
    observer.observe(ruler);
    let isActive = true;
    void document.fonts.ready.then(() => {
      if (isActive) measure();
    });
    return () => {
      isActive = false;
      observer.disconnect();
    };
  }, [isExpanded, text]);

  const isCollapsed = isCollapsible && !isExpanded;

  return (
    <div className="flex flex-col gap-1">
      {/* 두 상자 모두 `text-sm` 을 지녀야 `lh` 가 설명 글의 줄높이가 된다. */}
      <div id={contentId} className={cn("text-sm", isCollapsed && "max-h-[3lh] overflow-hidden")}>
        <div ref={rulerRef} className={cn("text-sm", !isExpanded && "max-h-[4lh] overflow-hidden")}>
          {children}
        </div>
      </div>
      {isCollapsible && (
        <button
          ref={buttonRef}
          type="button"
          aria-expanded={isExpanded}
          aria-controls={contentId}
          aria-label={isExpanded ? "상세 설명 접기" : "상세 설명 더 보기"}
          className="-mx-2 flex min-h-11 items-center gap-1.5 self-start rounded-md px-2 text-xs text-muted-foreground outline-none motion-safe:transition-colors hover:bg-secondary/50 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          onClick={() => setIsExpanded((open) => !open)}
        >
          <ChevronDown aria-hidden className={cn("size-4 motion-safe:transition-transform", isExpanded && "rotate-180")} />
          {isExpanded ? "접기" : "더 보기"}
        </button>
      )}
    </div>
  );
}
