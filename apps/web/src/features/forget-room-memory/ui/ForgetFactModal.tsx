import { useEffect, useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Eraser, Info, Loader2, TriangleAlert } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, type ChatRoomMemoryFact } from "@/entities/chat-room";
import { createSingleFlight } from "@/shared/lib/async/singleFlight";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useForgetFactMutation, useForgetFactPreviewQuery } from "../api/forgetMemoryMutations";
import { toForgetFailure, toPreviewFailure } from "../model/forgetFailure";
import type { ForgetOutcome } from "../model/forgetOutcome";
import { forgetFactConfirmLabel, MEMORY_COMEBACK_NOTICE } from "../model/memoryItemText";
import { FactSummary } from "./FactSummary";
import { MemoryNote } from "./MemoryNote";

type ForgetFactModalProps = {
  roomId: string;
  fact: ChatRoomMemoryFact;
};

/** 사실 하나를 잊게 하기 전 확인. 열자마자 함께 지워질 장면 수를 묻고, 답이 오기 전에는 실행 버튼을 막는다 — 비밀 사실은
 * 근거 대화와 겹치는 장면까지 지우는데, 그 수를 모른 채 누르게 하면 지울 범위를 알리지 않고 지운다. 수를 묻지 못하면
 * 실패 갈래(`toPreviewFailure`)대로 한다 — 그 기억이 이미 없거나 스위치가 꺼졌으면 해당 캐시를 다시 받게 하고 닫으며, 연결·서버
 * 오류에만 "다시 확인"을 두고, 그 밖에는 실행을 막은 채 닫기만 남긴다.
 *
 * 다시 생기는 길은 설명 안에 둔다(대화 상자의 설명으로 함께 읽힌다). 실행 버튼은 틴트(`destructive`)이고 막을 때는
 * `aria-disabled` 다(`disabled` 는 포커스를 빼앗는다). 버튼 순서는 `취소` 먼저(푸터 프리미티브가 강제). */
export const ForgetFactModal = createCallable<ForgetFactModalProps, ForgetOutcome>(({ call, roomId, fact }) => {
  const queryClient = useQueryClient();
  const preview = useForgetFactPreviewQuery(roomId, fact.factKey);
  const forget = useForgetFactMutation(roomId);
  const [error, setError] = useState<string | undefined>(undefined);
  // 같은 순간 두 번 누르면 `isPending`이 다시 그려지기 전에 두 번째가 들어와 요청이 둘 나간다 — 렌더를 기다리지 않고 막는다.
  const [runExclusive] = useState(createSingleFlight);

  const previewFailure = preview.isError ? toPreviewFailure(preview.error) : undefined;
  const previewFailureKind = previewFailure?.kind;
  const previewFailureMessage = previewFailure?.message;

  // 다시 물어도 풀리지 않는 두 갈래는 닫는다 — 목록 위 알림이 같은 문장을 남긴다.
  useEffect(() => {
    if (previewFailureMessage === undefined || call.ended) return;
    if (previewFailureKind === "gone") {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memoryItems(roomId) });
    } else if (previewFailureKind === "disabled") {
      void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
    } else {
      return;
    }
    call.end({ kind: "notice", message: previewFailureMessage });
  }, [call, previewFailureKind, previewFailureMessage, queryClient, roomId]);

  const episodeCount = preview.data?.episodeCount;
  const isConfirmBlocked = episodeCount === undefined || forget.isPending;

  async function handleConfirm() {
    await runExclusive(confirm);
  }

  async function confirm() {
    if (forget.isPending || episodeCount === undefined) return;
    setError(undefined);
    try {
      await forget.mutateAsync(fact.factKey);
      call.end({ kind: "forgotten", linkedEpisodeCount: episodeCount });
    } catch (caught) {
      const failure = toForgetFailure(caught, "forget");
      if (failure.kind === "message") {
        setError(failure.message);
        return;
      }
      if (failure.kind === "disabled") void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
      call.end({ kind: "notice", message: failure.message });
    }
  }

  let confirmLabel = "확인 중…";
  if (forget.isPending) confirmLabel = "잊게 하는 중…";
  else if (episodeCount !== undefined) confirmLabel = forgetFactConfirmLabel(episodeCount);

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end({ kind: "cancelled" })}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep">이 사실을 잊게 할까요?</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-3">
              <p>캐릭터가 이 사실을 더는 떠올리지 않아요. 지운 기억은 되돌릴 수 없어요.</p>
              <MemoryNote icon={Info}>{MEMORY_COMEBACK_NOTICE}</MemoryNote>
            </div>
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <FactSummary fact={fact} className="rounded-lg border border-border px-3 py-2.5" />
          {/* 수를 묻는 동안과 받은 뒤를 같은 자리에서 알린다 — 늘 마운트해 두어야 바뀐 문장이 읽힌다. */}
          <div aria-live="polite">
            <ForgetPreviewLine
              episodeCount={episodeCount}
              isPending={preview.isPending}
              errorMessage={previewFailureMessage}
              onRetry={previewFailureKind === "retry" ? () => void preview.refetch() : undefined}
            />
          </div>
          {error !== undefined && (
            <p role="alert" className="text-sm break-keep text-destructive-text">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end({ kind: "cancelled" })}>
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            aria-disabled={isConfirmBlocked}
            className="aria-disabled:opacity-65"
            onClick={() => void handleConfirm()}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});

type ForgetPreviewLineProps = {
  episodeCount: number | undefined;
  isPending: boolean;
  errorMessage: string | undefined;
  /** 없으면 "다시 확인"을 두지 않는다(다시 물어도 같은 거절이다). */
  onRetry: (() => void) | undefined;
};

function ForgetPreviewLine({ episodeCount, isPending, errorMessage, onRetry }: ForgetPreviewLineProps) {
  if (errorMessage !== undefined) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <MemoryNote icon={TriangleAlert} isEmphasized>
          {errorMessage}
        </MemoryNote>
        {onRetry && (
          <Button type="button" variant="outline" size="sm" className="hover:bg-secondary" onClick={onRetry}>
            다시 확인
          </Button>
        )}
      </div>
    );
  }
  if (isPending || episodeCount === undefined) {
    return (
      <p className="flex gap-2 text-xs break-keep text-muted-foreground">
        {/* 진행 표시라 줄인 모션에서도 돈다 — 멈추면 멈춘 화면으로 읽힌다. */}
        <Loader2 aria-hidden className="mt-px size-3.5 shrink-0 animate-spin" />
        함께 잊을 장면이 있는지 확인하는 중이에요.
      </p>
    );
  }
  if (episodeCount === 0) return null;
  return (
    <MemoryNote icon={Eraser} isEmphasized>
      이 사실과 이어진 <span className="font-semibold tabular-nums">장면 {episodeCount}개</span>도 함께 잊어요.
    </MemoryNote>
  );
}
