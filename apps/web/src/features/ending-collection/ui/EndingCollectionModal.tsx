import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { ArrowLeft, ChevronRight, Lock, Sparkles } from "lucide-react";

import {
  AuthorMacroNamesProvider,
  ChatMarkdown,
  MediaTagImagesProvider,
  useEndingCollectionQuery,
} from "@/entities/chat-room";
import type { EndingCollectionItem } from "@/entities/chat-room";
import { toMediaTagImages } from "@/entities/media-book";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { expandAuthorMacros, type AuthorMacroNames } from "@/shared/lib/text/authorMacros";

type EndingCollectionModalProps = {
  startingSetupId: string;
  /**
   * 엔딩 이름·힌트·에필로그 속 `{{user}}`·`{{char}}` 이름. 컬렉션은 방이 아니라 시작설정 단위지만, 여는 곳이 언제나
   * 대화방이라 그 방의 이름을 쓴다 — 방금 본 첫 메시지·에필로그와 같은 이름이다.
   */
  macroNames: AuthorMacroNames;
};

// "더보기 > 엔딩 컬렉션"에서 여는 읽기 전용 react-call
// 모달(PlayGuideModal과 동일하게 mutationFn/useMutationFlow 불필요). 목록↔에필로그 상세는 로컬
// state(selectedEnding)로 같은 Dialog 안에서 전환한다 — 새 Dialog를 중첩하지 않는다.
export const EndingCollectionModal = createCallable<EndingCollectionModalProps, void>(({ call, startingSetupId, macroNames }) => {
  const isOpen = !call.ended;
  const [selectedEnding, setSelectedEnding] = useState<EndingCollectionItem | undefined>(undefined);
  const endingsQuery = useEndingCollectionQuery(startingSetupId, isOpen);

  function handleOpenChange(next: boolean) {
    if (!next) {
      call.end();
      setSelectedEnding(undefined);
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      {/* 목록↔상세 래퍼는 `key` 로 바뀔 때마다 새로 마운트돼 진입 애니메이션을 다시 돌리고, 본문 스크롤도 맨 위에서
          시작한다. 애니메이션은 래퍼가 아니라 헤더와 본문 안쪽에 건다 — 래퍼째 옆으로 밀면 다이얼로그 전폭인 본문(경계선·
          스크롤바)이 다이얼로그 오른쪽 밖으로 삐져나온다. 안쪽 내용이 밀리는 8px 은 본문이 가로로 잘라 낸다. 본문에는
          포커스할 것이 없을 수 있어(잠긴 엔딩만 있는 목록, 에필로그 글) 본문 자체를 Tab 정지로 둔다. */}
      <DialogContent className="sm:max-w-sm">
        {selectedEnding ? (
          <div key={selectedEnding.id} className="flex min-h-0 flex-1 flex-col gap-4">
            <DialogHeader className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-2 motion-safe:duration-200">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedEnding(undefined)}
                className="-ml-2 w-fit hover:bg-secondary"
              >
                <ArrowLeft aria-hidden className="size-3.5" />
                목록으로
              </Button>
              <DialogTitle className="flex items-center gap-1.5">
                <Sparkles aria-hidden className="size-4 shrink-0 text-foreground" />
                {expandAuthorMacros(selectedEnding.name, macroNames)}
              </DialogTitle>
              <DialogDescription className="sr-only">엔딩 에필로그</DialogDescription>
            </DialogHeader>
            <DialogBody scrollLabel="에필로그">
              <div className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-right-2 motion-safe:duration-200">
                <EndingEpilogue
                  epilogue={selectedEnding.epilogue}
                  mediaTagImages={selectedEnding.mediaTagImages}
                  macroNames={macroNames}
                />
              </div>
            </DialogBody>
          </div>
        ) : (
          <div key="list" className="flex min-h-0 flex-1 flex-col gap-4">
            <DialogHeader className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
              <DialogTitle>엔딩 컬렉션</DialogTitle>
              <DialogDescription>지금까지 도달한 엔딩을 모아봤어요.</DialogDescription>
            </DialogHeader>
            <DialogBody scrollLabel="엔딩 목록">
              <div className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
                <EndingListBody query={endingsQuery} onSelect={setSelectedEnding} macroNames={macroNames} />
              </div>
            </DialogBody>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
});

type EndingEpilogueProps = {
  epilogue: EndingCollectionItem["epilogue"];
  mediaTagImages: EndingCollectionItem["mediaTagImages"];
  macroNames: AuthorMacroNames;
};

function EndingEpilogue({ epilogue, mediaTagImages, macroNames }: EndingEpilogueProps) {
  if (!epilogue) return <p className="text-sm text-foreground">이 엔딩에는 에필로그가 없어요.</p>;

  // 채팅방에서 본 에필로그와 같은 표기로 보인다(글 속 미디어 북 그림 포함). 다이얼로그 면 위라 코드 블록·그림 자리
  // 면은 secondary 다.
  return (
    <AuthorMacroNamesProvider names={macroNames}>
      <MediaTagImagesProvider images={toMediaTagImages(mediaTagImages)}>
        <ChatMarkdown content={epilogue} codeBlockSurface="secondary" />
      </MediaTagImagesProvider>
    </AuthorMacroNamesProvider>
  );
}

/** 네 상태(로딩·에러·목록·빈 목록)가 배타적이라 early return으로 순서를 강제한다.
 * 바깥의 `selectedEnding ? 상세 : 목록`은 2갈래라 삼항으로 남긴다 — 중첩이 문제였지 삼항 자체가
 * 아니다. */
function EndingListBody({
  query,
  onSelect,
  macroNames,
}: {
  query: ReturnType<typeof useEndingCollectionQuery>;
  onSelect: (ending: EndingCollectionItem) => void;
  macroNames: AuthorMacroNames;
}) {
  if (query.isPending) {
    return (
      <ul className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <li key={i} className="h-12 animate-pulse rounded-md bg-secondary" />
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
                className="flex w-full items-center gap-2.5 rounded-md py-2.5 text-left motion-safe:transition-colors hover:bg-secondary/50"
              >
                <Sparkles aria-hidden className="size-4 shrink-0 text-foreground" />
                <span className="flex-1 text-sm font-medium text-foreground">
                  {expandAuthorMacros(ending.name, macroNames)}
                </span>
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
                <span className="text-sm font-medium text-muted-foreground">
                  {expandAuthorMacros(ending.name, macroNames)}
                </span>
                <span className="text-xs text-muted-foreground/80">
                  {expandAuthorMacros(ending.hint ?? "아직 도달하지 못한 엔딩이에요.", macroNames)}
                </span>
              </div>
            </li>
          ),
        )}
      </ul>
  );
}
