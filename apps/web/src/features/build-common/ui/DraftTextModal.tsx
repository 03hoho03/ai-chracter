import { useRef } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Textarea } from "@ai-character-chat/ui/components/textarea";

import { createCallable } from "@/shared/lib/callable/createCallable";

type DraftTextModalProps = {
  text: string;
};

/**
 * 클립보드에 넣지 못했을 때(권한 거부, 클립보드가 없는 비보안 연결) [내용 복사]가 대신 여는 창. 글을 읽기 전용 글상자에 모두 선택해
 * 두어 작가가 복사 단축키 한 번으로 가져가게 한다. 열리면 닫기(X)가 아니라 글상자로 포커스가 간다 — 닫기가 글상자보다 앞에 그려져
 * 기본 포커스가 그리로 가기 때문이다.
 */
export const DraftTextModal = createCallable<DraftTextModalProps, void>(({ call, text }) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent
        className="sm:max-w-lg"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          textareaRef.current?.focus();
          textareaRef.current?.select();
        }}
      >
        <DialogHeader>
          <DialogTitle>작성한 글</DialogTitle>
          <DialogDescription>
            클립보드에 바로 넣지 못했어요. 아래 글이 모두 선택돼 있으니 복사해서 메모장 같은 곳에 붙여 두세요.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <Textarea
            ref={textareaRef}
            readOnly
            aria-label="작성한 글"
            value={text}
            className="min-h-48 text-sm"
            onFocus={(event) => event.currentTarget.select()}
          />
        </DialogBody>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            닫기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
