import { useEffect, useRef, type PointerEvent, type RefObject } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { Asterisk } from "lucide-react";

import { insertNarrationMarker } from "../model/insertNarrationMarker";

type NarrationMarkerButtonProps = {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  value: string;
  onValueChange: (next: string) => void;
  disabled?: boolean;
};

/**
 * 입력창 옆의 지문 표시(`*`) 버튼. 입력창은 제어 컴포넌트라 값을 바꾸면 React 가 다시 그리면서 캐럿이
 * 글 끝으로 튄다 — 다음 프레임에 캐럿을 되돌린다.
 */
export function NarrationMarkerButton({ textareaRef, value, onValueChange, disabled = false }: NarrationMarkerButtonProps) {
  // 한글처럼 조합 중인 입력이 있는지. 렌더에 쓰지 않는 값이라 state 가 아니라 ref 다.
  const isComposingRef = useRef(false);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const handleCompositionStart = () => {
      isComposingRef.current = true;
    };
    const handleCompositionEnd = () => {
      isComposingRef.current = false;
    };
    textarea.addEventListener("compositionstart", handleCompositionStart);
    textarea.addEventListener("compositionend", handleCompositionEnd);
    return () => {
      textarea.removeEventListener("compositionstart", handleCompositionStart);
      textarea.removeEventListener("compositionend", handleCompositionEnd);
    };
  }, [textareaRef]);

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    // 누르는 순간 입력창에서 포커스를 빼앗지 않는다 — 빼앗기면 모바일 키보드가 내려갔다가 다시 올라온다.
    // 단 조합 중이면 막지 않는다: 포커스가 남으면 조합 중인 음절이 확정되지 않은 채 값이 바뀌어 마지막 음절이
    // 겹치거나 사라질 수 있다. 포커스가 빠지면 브라우저가 조합을 확정하고, 이어지는 클릭이 확정된 글을 기준으로
    // 별표를 넣은 뒤 포커스를 돌려준다.
    if (!isComposingRef.current) event.preventDefault();
  }

  function handleClick() {
    const textarea = textareaRef.current;
    // 입력창 값이 기준이다 — 조합이 방금 확정됐다면 그 글자가 아직 이 컴포넌트의 `value` 에 반영되기 전일 수 있다.
    const text = textarea?.value ?? value;
    const next = insertNarrationMarker({
      text,
      selectionStart: textarea?.selectionStart ?? text.length,
      selectionEnd: textarea?.selectionEnd ?? text.length,
    });
    onValueChange(next.text);
    requestAnimationFrame(() => {
      textarea?.focus();
      textarea?.setSelectionRange(next.selectionStart, next.selectionEnd);
    });
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label="지문 표시 넣기"
      disabled={disabled}
      // 키보드(Tab → Enter)로 누를 때는 pointerdown 이 없고, 입력창이 흐려져도 선택 범위를 기억하므로 같은 결과다.
      onPointerDown={handlePointerDown}
      onClick={handleClick}
      className="text-muted-foreground"
    >
      <Asterisk aria-hidden className="size-4" />
    </Button>
  );
}
