import { useId, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";

export function CommentBody({ body }: { body: string }) {
  const id = useId();
  const ref = useRef<HTMLParagraphElement>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    function measure() {
      if (!element) return;
      const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight);
      setHasOverflow(element.scrollHeight > lineHeight * 6 + 1);
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [body]);
  return <div className="flex min-w-0 flex-col items-start gap-1">
    <p ref={ref} id={id} className={cn("whitespace-pre-wrap break-keep text-sm wrap-anywhere", !isExpanded && "line-clamp-6")}>{body}</p>
    {hasOverflow && <Button type="button" variant="ghost" size="sm" className="-ml-2"
      aria-expanded={isExpanded} aria-controls={id} onClick={(event) => {
        const button = event.currentTarget;
        setIsExpanded((current) => !current);
        if (isExpanded) requestAnimationFrame(() => button.scrollIntoView({ block: "nearest" }));
      }}>{isExpanded ? "접기" : "더 보기"}</Button>}
  </div>;
}
