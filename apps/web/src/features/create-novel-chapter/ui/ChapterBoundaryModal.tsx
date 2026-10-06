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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@ai-character-chat/ui/components/sheet";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useId, useRef, useState } from "react";

import { CloverSpendSummary, useCloverBalanceQuery } from "@/entities/clover";
import {
  ChapterModelSelect,
  chapterModelCost,
  initialChapterModelId,
  type NovelChapterModelId,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import type { NovelChapterProposal } from "../api/useChapterProposalMutation";
import { useIsChapterBoundaryDialogLayout } from "../lib/useIsChapterBoundaryDialogLayout";
import { toInitialChapterEnd } from "../model/chapterBoundarySelection";

type ChapterBoundaryModalProps = {
  proposal: NovelChapterProposal;
  /** 만들 장의 번호(지금 마지막 장 + 1). */
  chapterOrdinal: number;
  /** 이 소설이 직전에 쓴 글쓰기 모델(상세의 값). 모델 선택이 이 값으로 골라진 채 열린다. */
  lastChapterModel: NovelChapterModelId | undefined;
};

/** 확정한 끝 턴, 그 장을 쓸 모델, 이용자가 본 금액. 모델 선택이 보이지 않는 계정도 요청에는 늘 모델을 싣는다(기본
 * 모델). 금액을 함께 돌려주는 이유는 요청의 `expectedCost` 가 화면에 보인 숫자와 같은 값이어야 해서다. */
export type ChapterBoundaryChoice = { endMessageId: string; model: NovelChapterModelId; cost: number };

const LIST_LABEL = "고를 수 있는 턴";

/** 다음 장을 어느 턴에서 끝낼지 고르고, 그 자리에서 금액을 확인한다. 고른 턴의 AI 응답 id 와 쓸 모델을 돌려주고,
 * 그만두면 `null` 이다.
 *
 * 금액 확인을 따로 띄우지 않고 여기서 받는 이유: 장 생성은 경계를 확인하는 단계에서 금액을 보이고 동의를 받기로
 * 했다. 고른 직후 같은 화면에 "클로버 N개를 써요"와 잔액이 있으니 실행 버튼이 곧 동의이고, 모달을 하나 더 띄우면
 * 같은 결정을 두 번 묻는다. 단가는 제안 응답의 이 순간 서버 값이다 — 고른 모델의 가격(`chapterModels`), 그 목록이
 * 없는 서버면 `cost`.
 *
 * 소설 상위 모델 허용이 있으면 금액 줄 위에 모델 선택이 생기고, 금액이 고른 모델을 따라 바뀐다. 허용이 없으면 모델이
 * 하나뿐이라 선택이 그려지지 않는다.
 *
 * 좁은 화면은 아래 시트, 넓은 화면은 가운데 다이얼로그다 — 둘 중 하나만 마운트한다(포털·포커스 가둠 때문에 공존할
 * 수 없다). 고른 값은 이 컴포넌트가 쥐므로 열린 채 화면 폭이 바뀌어도 남는다. */
export const ChapterBoundaryModal = createCallable<ChapterBoundaryModalProps, ChapterBoundaryChoice | null>(
  ({ call, proposal, chapterOrdinal, lastChapterModel }) => {
    const isDialogLayout = useIsChapterBoundaryDialogLayout();
    const { data: clover } = useCloverBalanceQuery();
    const [selectedId, setSelectedId] = useState(() => toInitialChapterEnd(proposal));
    const models = proposal.chapterModels ?? [];
    const [modelId, setModelId] = useState(() => initialChapterModelId(models, lastChapterModel));
    const cost = chapterModelCost(models, modelId, "generate", proposal.cost);
    // 고르지 않고 실행을 눌렀을 때의 안내. 한 번 띄우면 고를 때까지 남는다(렌더 때 파생하지 않는다 — 처음 열었을
    // 때부터 "골라주세요" 오류가 떠 있으면 아직 아무것도 안 한 이용자를 탓하는 셈이다).
    const [isSelectionMissing, setIsSelectionMissing] = useState(false);
    const listRef = useRef<HTMLDivElement>(null);
    const errorId = useId();

    const title = `${chapterOrdinal}장을 어디까지 담을까요?`;
    const suggestedOrdinal = proposal.candidates.find(
      (candidate) => candidate.messageId === proposal.suggestion?.endMessageId,
    )?.ordinal;
    const description =
      suggestedOrdinal === undefined
        ? "끝낼 턴을 골라주세요. 고른 턴까지의 대화가 한 장이 돼요."
        : `AI가 ${suggestedOrdinal}번째 턴에서 끊기를 제안했어요. 그대로 두거나 다른 턴을 골라주세요.`;

    function handleSelect(value: string) {
      // 단일 토글 그룹은 고른 항목을 다시 누르면 빈 값을 보낸다 — 끝 턴은 늘 하나라 해제를 받지 않는다.
      if (value === "") return;
      setSelectedId(value);
      setIsSelectionMissing(false);
    }

    function handleConfirm() {
      if (selectedId === undefined) {
        setIsSelectionMissing(true);
        return;
      }
      call.end({ endMessageId: selectedId, model: modelId, cost });
    }

    // 열리면 골라 둔 턴(없으면 첫 턴)으로 포커스를 보낸다 — 기본 동작은 닫기 X 로 가고, 제안 턴이 목록 아래쪽이면
    // 보이지도 않는다. 포커스가 그 항목을 스크롤해 보여 준다.
    function focusSelection(event: Event) {
      const target =
        listRef.current?.querySelector<HTMLElement>('[data-state="on"]') ??
        listRef.current?.querySelector<HTMLElement>("button");
      if (!target) return;
      event.preventDefault();
      target.focus();
    }

    const list = (
      <div ref={listRef} className="flex flex-col gap-1.5">
        <ToggleGroup
          type="single"
          variant="list"
          orientation="vertical"
          value={selectedId ?? ""}
          onValueChange={handleSelect}
          aria-label="장을 끝낼 턴"
          aria-invalid={isSelectionMissing}
          aria-describedby={isSelectionMissing ? errorId : undefined}
          className="w-full"
        >
          {proposal.candidates.map((candidate) => {
            const isSuggested = candidate.messageId === proposal.suggestion?.endMessageId;
            return (
              // 행이 발췌 두 줄까지 품도록 높이·줄바꿈을 풀고 왼쪽 정렬한다. `hover:bg-secondary` — 프리미티브의
              // `hover:bg-muted` 는 모달·시트 표면(`popover`)과 같은 값이라 사라진다.
              <ToggleGroupItem
                key={candidate.messageId}
                value={candidate.messageId}
                className="h-auto w-full flex-col items-start justify-start gap-1 px-3 py-2.5 text-left whitespace-normal hover:bg-secondary"
              >
                <span className="flex items-center gap-2">
                  <span className="font-semibold tabular-nums">{candidate.ordinal}번째 턴</span>
                  {isSuggested && (
                    <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium">
                      제안
                    </span>
                  )}
                </span>
                <span className="line-clamp-2 text-sm font-normal break-keep text-muted-foreground">
                  {candidate.excerpt}
                </span>
                {isSuggested && proposal.suggestion && (
                  <span className="text-xs font-normal break-keep text-muted-foreground">
                    제안 이유: {proposal.suggestion.reason}
                  </span>
                )}
              </ToggleGroupItem>
            );
          })}
        </ToggleGroup>
        {isSelectionMissing && (
          <p id={errorId} role="alert" className="text-xs text-destructive-text">
            끝낼 턴을 골라주세요
          </p>
        )}
      </div>
    );

    const summary = (
      <>
        <ChapterModelSelect models={models} value={modelId} onValueChange={setModelId} kind="generate" />
        <CloverSpendSummary cost={cost} balance={clover?.balance} />
      </>
    );
    const confirmLabel = `${chapterOrdinal}장 만들기`;

    if (isDialogLayout) {
      return (
        <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
          <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusSelection}>
            <DialogHeader>
              <DialogTitle className="break-keep">{title}</DialogTitle>
              <DialogDescription className="break-keep">{description}</DialogDescription>
            </DialogHeader>
            <DialogBody scrollLabel={LIST_LABEL}>{list}</DialogBody>
            {/* 금액은 목록 밖에 고정한다 — 목록을 내려 읽는 동안에도 누르면 얼마가 빠지는지가 보인다. */}
            {summary}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end(null)}>
                취소
              </Button>
              <Button type="button" onClick={handleConfirm}>
                {confirmLabel}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      );
    }

    return (
      <Sheet open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
        {/* 높이는 내용만큼, 상한은 헤더 아래까지 — 길면 목록만 스크롤하고 금액·버튼은 바닥에 남는다. */}
        <SheetContent side="bottom" className="max-h-below-header gap-0 rounded-t-xl" onOpenAutoFocus={focusSelection}>
          <SheetHeader className="pr-12">
            <SheetTitle className="break-keep">{title}</SheetTitle>
            <SheetDescription className="break-keep">{description}</SheetDescription>
          </SheetHeader>
          {/* 다이얼로그의 `DialogBody scrollLabel` 과 같은 몫 — 닫기 X 가 목록 밖이라 목록 자체가 Tab 정지이자 이름
              있는 영역이어야 키보드로 스크롤할 수 있다. 포커스 표시도 같은 안쪽 outline 이다. */}
          <div
            role="region"
            aria-label={LIST_LABEL}
            tabIndex={0}
            className="min-h-0 flex-1 overflow-y-auto border-t px-4 py-4 outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
          >
            {list}
          </div>
          <SheetFooter className="mt-0 gap-3 border-t">
            {summary}
            <div className="flex gap-2">
              <Button type="button" variant="outline" className="flex-1" onClick={() => call.end(null)}>
                취소
              </Button>
              <Button type="button" className="flex-1" onClick={handleConfirm}>
                {confirmLabel}
              </Button>
            </div>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    );
  },
);
