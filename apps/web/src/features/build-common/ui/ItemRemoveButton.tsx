import { Button } from "@ai-character-chat/ui/components/button";
import { Trash2 } from "lucide-react";
import type { MouseEventHandler } from "react";

type ItemRemoveButtonProps = {
  /** 무엇을 지우는지 담은 이름(예: `도희 호감도 스탯 삭제`). 같은 이름의 삭제 버튼이 목록에 반복되지 않게 항목을 가른다. */
  label: string;
  onClick: MouseEventHandler<HTMLButtonElement>;
};

/** 접기 머리 줄 오른쪽 끝의 삭제 버튼. 터치 화면에서는 40px 로 올린다(머리 줄 높이도 같이 40px 가 된다). */
export function ItemRemoveButton({ label, onClick }: ItemRemoveButtonProps) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={label}
      onClick={onClick}
      className="pointer-coarse:size-10"
    >
      <Trash2 aria-hidden />
    </Button>
  );
}
