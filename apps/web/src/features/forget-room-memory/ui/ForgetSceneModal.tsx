import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Info } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, type ChatRoomMemoryEpisode } from "@/entities/chat-room";
import { createSingleFlight } from "@/shared/lib/async/singleFlight";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useForgetEpisodeMutation } from "../api/forgetMemoryMutations";
import { toForgetFailure } from "../model/forgetFailure";
import type { ForgetOutcome } from "../model/forgetOutcome";
import { forgetSceneTitle, MEMORY_COMEBACK_NOTICE } from "../model/memoryItemText";
import { MemoryNote } from "./MemoryNote";

type ForgetSceneModalProps = {
  roomId: string;
  episode: ChatRoomMemoryEpisode;
};

/** 장면 기억 하나를 잊게 하기 전 확인. 성공 뒤 할 일(목록 다시 받기)이 늘 같아 대화가 직접 지운다.
 *
 * 다시 생기는 길과 요약에 남은 내용은 설명 안에 둔다 — 대화 상자의 설명으로 함께 읽힌다. 실행 버튼은 틴트(`destructive`)이고
 * 요청 중에는 `aria-disabled` 로 막는다(`disabled` 는 포커스를 빼앗는다). 버튼 순서는 `취소` 먼저(푸터 프리미티브가 강제). */
export const ForgetSceneModal = createCallable<ForgetSceneModalProps, ForgetOutcome>(({ call, roomId, episode }) => {
  const queryClient = useQueryClient();
  const forget = useForgetEpisodeMutation(roomId);
  const [error, setError] = useState<string | undefined>(undefined);
  // 같은 순간 두 번 누르면 `isPending`이 다시 그려지기 전에 두 번째가 들어와 요청이 둘 나간다 — 렌더를 기다리지 않고 막는다.
  const [runExclusive] = useState(createSingleFlight);

  async function handleConfirm() {
    await runExclusive(confirm);
  }

  async function confirm() {
    if (forget.isPending) return;
    setError(undefined);
    try {
      await forget.mutateAsync(episode.id);
      call.end({ kind: "forgotten", linkedEpisodeCount: 0 });
    } catch (caught) {
      const failure = toForgetFailure(caught, "forget");
      if (failure.kind === "message") {
        setError(failure.message);
        return;
      }
      // 스위치가 꺼졌으면 기억 응답을 다시 받아 패널을 목록 없는 모양으로 돌린다. 이미 없는 기억이면 목록은 뮤테이션이
      // 다시 받았다.
      if (failure.kind === "disabled") void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) });
      call.end({ kind: "notice", message: failure.message });
    }
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(open) => !open && call.end({ kind: "cancelled" })}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-keep wrap-break-word">{forgetSceneTitle(episode.title)}</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-3">
              <p>캐릭터가 이 장면을 더는 떠올리지 않아요. 지운 기억은 되돌릴 수 없어요.</p>
              <MemoryNote icon={Info}>{MEMORY_COMEBACK_NOTICE}</MemoryNote>
              <MemoryNote icon={Info}>요약에 같은 내용이 남아 있으면 요약을 직접 고쳐 주세요.</MemoryNote>
            </div>
          </DialogDescription>
        </DialogHeader>

        {error !== undefined && (
          <p role="alert" className="text-sm break-keep text-destructive-text">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end({ kind: "cancelled" })}>
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            aria-disabled={forget.isPending}
            className="aria-disabled:opacity-65"
            onClick={() => void handleConfirm()}
          >
            {forget.isPending ? "잊게 하는 중…" : "잊게 하기"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
