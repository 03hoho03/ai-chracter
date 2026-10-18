import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useState } from "react";

import { createCallable } from "@/shared/lib/callable/createCallable";

import { useWithdrawNovelPublicationMutation } from "../api/useWithdrawNovelPublicationMutation";

/** 거두기와 신청 취소의 문구. 둘은 같은 요청이다 — 서버가 승인 대기면 신청을 지우고 아니면 거둔다. 신청 취소는 아무에게도
 * 보인 적 없는 글이라 잃는 것이 없어 실행 버튼을 `outline` 으로 두고, 잃는 것이 있는 거두기만 `destructive` 틴트다. */
const COPY = {
  withdraw: {
    title: "노벨 공개를 거둘까요?",
    description:
      "목록과 작품 화면에서 바로 사라지고, 소장한 회원도 더 볼 수 없게 돼요. 클로버는 돌려드리지 않아요. 나중에 다시 공개하면 소장한 화도 다시 열려요.",
    confirm: "공개 거두기",
    pending: "거두는 중…",
    error: "공개를 거두지 못했어요. 잠시 후 다시 시도해 주세요.",
    variant: "destructive",
  },
  cancelReview: {
    title: "공개 신청을 취소할까요?",
    description: "아직 아무에게도 보이지 않았어요. 취소하면 신청이 없어지고 언제든 다시 신청할 수 있어요.",
    confirm: "신청 취소하기",
    pending: "취소하는 중…",
    error: "신청을 취소하지 못했어요. 잠시 후 다시 시도해 주세요.",
    variant: "outline",
  },
} as const;

type WithdrawNovelPublicationModalProps = {
  novelId: string;
  mode: keyof typeof COPY;
};

/** 노벨 공개 거두기·신청 취소 확인. 거두기는 목록·작품 화면에서 바로 사라지고 소장한 회원도 못 보며 클로버는 돌려주지
 * 않는다는 것을, 다시 공개하면 소장한 화가 다시 열린다는 것과 함께 확정 전에 말한다. 요청이 끝났으면 `true` — 신청
 * 취소였는지 그사이 승인돼 거두기가 됐는지는 호출부가 다시 받은 공개 상태로 가른다. */
export const WithdrawNovelPublicationModal = createCallable<WithdrawNovelPublicationModalProps, boolean>(({ call, novelId, mode }) => {
  const withdraw = useWithdrawNovelPublicationMutation(novelId);
  const copy = COPY[mode];
  const [error, setError] = useState<string | undefined>(undefined);

  async function handleWithdraw() {
    if (withdraw.isPending) return;
    setError(undefined);
    try {
      await withdraw.mutateAsync();
      call.end(true);
    } catch {
      setError(copy.error);
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(false)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription className="break-keep">{copy.description}</DialogDescription>
        </DialogHeader>

        {error !== undefined && (
          <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end(false)}>
            취소
          </Button>
          <Button
            type="button"
            variant={copy.variant}
            aria-disabled={withdraw.isPending}
            className="aria-disabled:opacity-65"
            onClick={() => void handleWithdraw()}
          >
            {withdraw.isPending ? copy.pending : copy.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
