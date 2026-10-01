import { Button } from "@ai-character-chat/ui/components/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@ai-character-chat/ui/components/dialog";
import { Link } from "@tanstack/react-router";
import { createCallable } from "react-call";
import { useAtom } from "jotai";

import { contentDetailModalAtom } from "@/entities/content";

export const CommentLoginModal = createCallable<{ returnFocus: () => void }, void>(({ call, returnFocus }) => {
  const [modalState, setModalState] = useAtom(contentDetailModalAtom);
  const redirect = window.location.pathname + window.location.search;
  return (
  <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
    <DialogContent className="sm:max-w-sm"
      onCloseAutoFocus={(event) => { event.preventDefault(); requestAnimationFrame(returnFocus); }}>
      <DialogHeader>
        <DialogTitle>로그인 후 참여할 수 있어요</DialogTitle>
        <DialogDescription className="break-keep">댓글과 좋아요를 남기려면 로그인해주세요. 이 안내를 닫아도 작성 중인 내용은 그대로 남아요.</DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => call.end()}>계속 둘러보기</Button>
        <Button asChild><Link to="/login" search={{ redirect }} replace={modalState !== undefined} onClick={() => { setModalState(undefined); call.end(); }}>로그인</Link></Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
);
});
