import { Button } from "@ai-character-chat/ui/components/button";

/** 빌더 되돌리기 토스트의 표시 시간. 기본 4초는 바뀐 것을 알아채고 되돌리기를 누르기에 짧다. */
export const UNDO_TOAST_DURATION_MS = 8000;

type UndoToastButtonProps = {
  onClick: () => void;
};

/**
 * 빌더 되돌리기 토스트(미디어 북 칸 이미지 교체, 반복 항목 삭제)의 동작 버튼. 모든 되돌리기 토스트가 같은 모양이도록 여기
 * 하나만 둔다.
 * sonner 의 기본 동작 버튼은 밝은 면·작은 반경·다크에서 안 보이는 포커스라 이 앱의 버튼을 넘긴다. 토스트 면이 popover 라
 * outline 의 hover 채움(muted)이 사라지므로 secondary 로 올린다.
 */
export function UndoToastButton({ onClick }: UndoToastButtonProps) {
  return (
    <Button type="button" variant="outline" size="sm" className="ml-auto hover:bg-secondary" onClick={onClick}>
      되돌리기
    </Button>
  );
}
