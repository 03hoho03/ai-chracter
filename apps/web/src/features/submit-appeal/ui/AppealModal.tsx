import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Button } from "@ai-character-chat/ui/components/button";
import { Textarea } from "@ai-character-chat/ui/components/textarea";
import { createCallable } from "react-call";
import { toast } from "sonner";

import { useSubmitAppealMutation, type AppealTarget } from "../api/useSubmitAppealMutation";

type Props = {
  target: AppealTarget;
};

/** techspec-builder-common.md §5.1 — 발행 거부 화면의 "이의제기" 버튼(US-098)과 조치 통지(US-055)
 * 두 진입점이 target만 다르게 넘겨 공유하는 react-call 모달. UpdateInfoModal과 동일하게 자체
 * mutation을 직접 호출하는 완결형 컴포넌트다(호출부마다 달라질 후속 동작이 없어 ReportContentModal의
 * caller-supplied mutationFn 패턴은 불필요). */
export const AppealModal = createCallable<Props, void>(({ call, target }) => {
  const [reasonText, setReasonText] = useState("");
  const submitAppeal = useSubmitAppealMutation();

  function handleSubmit() {
    submitAppeal.mutate(
      { target, reasonText },
      {
        onSuccess: () => {
          toast.success("이의제기가 접수되었어요. 검토 후 결과를 안내해드릴게요.");
          call.end();
        },
        onError: () => toast.error("이의제기 접수에 실패했어요. 잠시 후 다시 시도해주세요."),
      },
    );
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>이의제기</DialogTitle>
          <DialogDescription>이의제기 사유를 자유롭게 작성해주세요.</DialogDescription>
        </DialogHeader>

        <Textarea
          value={reasonText}
          onChange={(event) => setReasonText(event.target.value)}
          placeholder="이의제기 사유를 입력해주세요."
          rows={5}
          aria-label="이의제기 사유"
        />

        <DialogFooter>
          <Button
            className="w-full"
            disabled={!reasonText.trim() || submitAppeal.isPending}
            onClick={handleSubmit}
          >
            {submitAppeal.isPending ? "접수 중..." : "이의제기 접수"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
