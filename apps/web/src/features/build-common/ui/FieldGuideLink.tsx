import { Button } from "@ai-character-chat/ui/components/button";
import { CircleHelp } from "lucide-react";

type FieldGuideLinkProps = {
  /** 작성 가이드의 그 칸 자리 — 단계 페이지이거나, 칸 블록이 있는 원고면 그 블록 앵커까지. */
  href: string;
  /** 접근 이름에 들어갈 칸 이름(화면 라벨과 같은 글자). */
  fieldLabel: string;
};

/**
 * 칸 라벨 옆의 `?` — 그 칸을 설명하는 작성 가이드 자리를 새 탭으로 연다. 칸 아래 한 줄 도움말은 칸이 무엇에 쓰이는지만
 * 말하고, 어떻게 쓰는지는 이 링크가 가이드로 넘긴다.
 *
 * 새 탭인 이유는 상단바의 작성 가이드 링크와 같다 — 같은 탭에서 이동하면 쓰던 폼을 떠난다(그래서 라우터 `Link` 가 아니라
 * 평범한 `<a>` 다). 폼 액션이 아니라 이동이라 보더 없는 ghost 이고, 24px 은 라벨 줄 높이를 늘리지 않으면서 포인터 타깃
 * 최소 크기를 지키는 값이다.
 */
export function FieldGuideLink({ href, fieldLabel }: FieldGuideLinkProps) {
  return (
    <Button asChild variant="ghost" size="icon-xs" className="text-muted-foreground">
      <a href={href} target="_blank" rel="noopener noreferrer" aria-label={`${fieldLabel} 작성 가이드 (새 탭에서 열림)`}>
        <CircleHelp aria-hidden className="size-3.5" />
      </a>
    </Button>
  );
}
