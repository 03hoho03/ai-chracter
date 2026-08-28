import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { ArrowLeft, ChevronRight, Lock, Sparkles } from "lucide-react";
import { createCallable } from "react-call";

import { useEndingCollectionQuery } from "@/entities/chat-room";
import type { EndingCollectionItem } from "@/entities/chat-room";

type Props = {
  startingSetupId: string;
};

// techspec-chat-story.md §6, US-069/070 — "더보기 > 엔딩 컬렉션"에서 여는 읽기 전용 react-call
// 모달(PlayGuideModal과 동일하게 mutationFn/useMutationFlow 불필요). 목록↔에필로그 상세는 로컬
// state(selectedEnding)로 같은 Dialog 안에서 전환한다 — 새 Dialog를 중첩하지 않는다.
export const EndingCollectionModal = createCallable<Props, void>(({ call, startingSetupId }) => {
  const open = !call.ended;
  const [selectedEnding, setSelectedEnding] = useState<EndingCollectionItem | null>(null);
  const endingsQuery = useEndingCollectionQuery(startingSetupId, open);

  function handleOpenChange(next: boolean) {
    if (!next) {
      call.end();
      setSelectedEnding(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-sm">
        {selectedEnding ? (
          <div key={selectedEnding.id} className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-2 motion-safe:duration-200">
            <DialogHeader>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedEnding(null)}
                className="-ml-2 w-fit"
              >
                <ArrowLeft aria-hidden className="size-3.5" />
                목록으로
              </Button>
              <DialogTitle className="flex items-center gap-1.5">
                <Sparkles aria-hidden className="size-4 shrink-0 text-foreground" />
                {selectedEnding.name}
              </DialogTitle>
              <DialogDescription className="sr-only">엔딩 에필로그</DialogDescription>
            </DialogHeader>
            <p className="whitespace-pre-wrap text-sm text-foreground">
              {selectedEnding.epilogue ?? "이 엔딩에는 에필로그가 없어요."}
            </p>
          </div>
        ) : (
          <div key="list" className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
            <DialogHeader>
              <DialogTitle>엔딩 컬렉션</DialogTitle>
              <DialogDescription>지금까지 도달한 엔딩을 모아봤어요.</DialogDescription>
            </DialogHeader>

            <EndingListBody query={endingsQuery} onSelect={setSelectedEnding} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
});

/** 네 상태(로딩·에러·목록·빈 목록)가 배타적이라 early return으로 순서를 강제한다(COMP-04).
 * 바깥의 `selectedEnding ? 상세 : 목록`은 2갈래라 삼항으로 남긴다 — 중첩이 문제였지 삼항 자체가
 * 아니다. */
function EndingListBody({
  query,
  onSelect,
}: {
  query: ReturnType<typeof useEndingCollectionQuery>;
  onSelect: (ending: EndingCollectionItem) => void;
}) {
  if (query.isPending) {
    return (
      <ul className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <li key={i} className="h-12 animate-pulse rounded-md bg-muted" />
        ))}
      </ul>
    );
  }

  if (query.isError) {
    return (
      <p className="py-4 text-center text-sm text-destructive-text">
        불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const endings = query.data;
  if (endings === undefined || endings.length === 0) {
    return (
      <p className="py-4 text-center text-sm text-muted-foreground">등록된 엔딩이 없어요.</p>
    );
  }

  return (
      <ul className="flex flex-col">
        {endings.map((ending) =>
          ending.reached ? (
            <li key={ending.id} className="border-b border-border last:border-b-0">
              <button
                type="button"
                onClick={() => onSelect(ending)}
                className="flex w-full items-center gap-2.5 rounded-md py-2.5 text-left transition-colors hover:bg-secondary/50"
              >
                <Sparkles aria-hidden className="size-4 shrink-0 text-foreground" />
                <span className="flex-1 text-sm font-medium text-foreground">{ending.name}</span>
                <ChevronRight aria-hidden className="size-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          ) : (
            <li
              key={ending.id}
              className="flex items-start gap-2.5 border-b border-border py-2.5 last:border-b-0"
            >
              <Lock aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground/60" />
              <div className="flex flex-1 flex-col gap-0.5">
                <span className="text-sm font-medium text-muted-foreground">{ending.name}</span>
                <span className="text-xs text-muted-foreground/80">
                  {ending.hint ?? "아직 도달하지 못한 엔딩이에요."}
                </span>
              </div>
            </li>
          ),
        )}
      </ul>
  );
}
