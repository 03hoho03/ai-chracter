import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { createCallable } from "react-call";
import { toast } from "sonner";

import type { Persona } from "@/entities/persona";

import { useDeletePersonaMutation } from "../api/useDeletePersonaMutation";
import { personaErrorMessage } from "../model/personaErrorMessage";

type DeletePersonaModalProps = {
  persona: Persona;
  isDefault: boolean;
};

/** 자체 호출형 react-call — 삭제 뒤 동작(목록·방 캐시 갱신 + 토스트)이 호출부와 무관하게 같다.
 * persona-goal-prompt.md UP-14 — 참조하던 방은 "선택 안 함"이 되고, 기본이었으면 기본도 없어진다. */
export const DeletePersonaModal = createCallable<DeletePersonaModalProps, void>(({ call, persona, isDefault }) => {
  const deleteMutation = useDeletePersonaMutation();

  function handleDelete() {
    if (deleteMutation.isPending) return;
    deleteMutation.mutate(persona.id, {
      onSuccess: () => {
        toast.success("대화 프로필을 삭제했어요.");
        call.end();
      },
      onError: (error) => toast.error(personaErrorMessage(error)),
    });
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle className="break-all">'{persona.name}' 프로필을 삭제할까요?</DialogTitle>
          <DialogDescription className="break-keep">
            이 프로필을 쓰던 대화방은 '선택 안 함'으로 바뀌어요.
            {isDefault && " 기본 프로필도 없어져요."} 지난 대화 내용은 그대로예요.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button
            type="button"
            variant="destructive"
            aria-disabled={deleteMutation.isPending}
            className="aria-disabled:opacity-65"
            onClick={handleDelete}
          >
            {deleteMutation.isPending ? "삭제 중..." : "삭제"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});
