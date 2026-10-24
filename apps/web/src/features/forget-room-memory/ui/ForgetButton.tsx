import { Button } from "@ai-character-chat/ui/components/button";
import { Eraser } from "lucide-react";

/** 행 끝의 지우개. 32px 이지만 손가락으로 누르는 기기에서는 40px 로 키운다(빌더 행 버튼과 같다). 카드·대화 상자 표면에서
 * `ghost`의 hover 채움(`muted`)은 사라지므로 `secondary`로 올린다. */
export function ForgetButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      className="-mr-1.5 shrink-0 text-muted-foreground hover:bg-secondary hover:text-foreground pointer-coarse:size-10"
      onClick={onClick}
    >
      <Eraser aria-hidden className="size-4" />
    </Button>
  );
}
