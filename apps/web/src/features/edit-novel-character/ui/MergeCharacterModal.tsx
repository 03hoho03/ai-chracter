import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { Label } from "@ai-character-chat/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { novelKeys, useMergeNovelCharacterMutation, type NovelCharacterResponse } from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { toCharacterSaveError } from "../model/characterForm";

type MergeCharacterModalProps = {
  novelId: string;
  /** 흡수될 카드 — 합치면 사라진다. */
  character: Pick<NovelCharacterResponse, "id" | "name">;
  /** 남을 카드로 고를 수 있는 다른 인물들. */
  candidates: Pick<NovelCharacterResponse, "id" | "name">[];
};

/**
 * 같은 인물의 이름 표기가 갈려 생긴 카드를 합친다. 남을 카드를 고르면 이 카드의 이름·별칭은 그 카드의 별칭이 되고,
 * 메모는 그 카드 메모 뒤에 `[이 이름] 메모` 로 붙고, 나온 화가 옮겨진 뒤 이 카드는 사라진다 — 되돌리는 길은 버전
 * 되돌리기뿐이라 확정 전에 그 결과를 문장으로 말한다. 합친 뒤 남은 카드의 id 를 돌려주고(이 카드가 사라져 호출부가
 * 그 카드를 고르고 포커스를 옮긴다), 그만두면 `null` 이다.
 */
export const MergeCharacterModal = createCallable<MergeCharacterModalProps, string | null>(
  ({ call, novelId, character, candidates }) => {
    const queryClient = useQueryClient();
    const selectId = useId();
    const mutation = useMergeNovelCharacterMutation();
    const [intoId, setIntoId] = useState<string | undefined>(undefined);
    const [error, setError] = useState<string | undefined>(undefined);
    const into = candidates.find((candidate) => candidate.id === intoId);
    const isMerging = mutation.isPending;

    async function handleMerge() {
      if (isMerging) return;
      if (into === undefined) {
        setError("함께 합칠 인물을 골라주세요");
        return;
      }
      setError(undefined);
      try {
        await mutation.mutateAsync({ novelId, characterId: character.id, intoCharacterId: into.id });
        call.end(into.id);
      } catch (mergeError) {
        const notice = toCharacterSaveError(mergeError, "mergeCharacter");
        if (notice === null) {
          call.end(null);
          return;
        }
        setError(notice.message);
        // 어느 카드가 사라졌으면 목록이 낡았다 — 다시 받아 고를 수 있는 인물을 맞춘다.
        if (notice.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.characters(novelId) });
      }
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="break-keep">‘{character.name}’을 다른 인물과 합칠까요?</DialogTitle>
            <DialogDescription className="break-keep">
              {into === undefined
                ? "같은 인물인데 이름이 다르게 나와 카드가 둘이 됐을 때 써요. 남길 인물을 골라주세요."
                : `‘${character.name}’ 카드는 사라지고, 이름은 ‘${into.name}’의 별칭이 돼요. 메모는 ‘${into.name}’ 메모 뒤에 [${character.name}] 메모로 붙고, 나온 화도 함께 옮겨져요.`}
            </DialogDescription>
          </DialogHeader>

          <div className="flex flex-col gap-2">
            <Label htmlFor={selectId}>남길 인물</Label>
            <Select
              value={intoId ?? ""}
              onValueChange={(value) => {
                setIntoId(value);
                setError(undefined);
              }}
            >
              <SelectTrigger id={selectId} aria-invalid={error !== undefined && into === undefined}>
                <SelectValue placeholder="인물 고르기" />
              </SelectTrigger>
              <SelectContent>
                {candidates.map((candidate) => (
                  <SelectItem key={candidate.id} value={candidate.id}>
                    {candidate.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {error !== undefined && (
            <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
              {error}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => call.end(null)}>
              취소
            </Button>
            <Button type="button" aria-disabled={isMerging} className="aria-disabled:opacity-65" onClick={() => void handleMerge()}>
              {isMerging ? "합치는 중…" : "합치기"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  },
);
