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
import { Loader2 } from "lucide-react";
import { useId, useRef, useState } from "react";

import { CloverSpendSummary, useCloverBalanceQuery } from "@/entities/clover";
import {
  ChapterModelSelect,
  hasChapterModelChoice,
  toEpisodeRangeLabel,
  toNovelActionError,
  useNovelChainEstimateQuery,
  type ChapterModelOption,
  type NovelChapterModelId,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { useChapterProposalMutation, type NovelChapterProposal } from "../api/useChapterProposalMutation";
import { useIsChapterBoundaryDialogLayout } from "../lib/useIsChapterBoundaryDialogLayout";
import {
  CHAIN_CHOICE_VALUE,
  toChainChoice,
  toFreshChainEstimates,
  toSelectionAfterModelChange,
} from "../model/chainChoice";
import { toInitialChapterEnd } from "../model/chapterBoundarySelection";

type ChapterBoundaryModalProps = {
  novelId: string;
  /** `initialModelId` 로 받은 제안. 모델을 바꾸면 모달이 그 모델로 다시 받는다. */
  proposal: NovelChapterProposal;
  /** 고를 수 있는 글쓰기 모델. 하나뿐이면 모델 선택이 그려지지 않는다. */
  modelOptions: ChapterModelOption[];
  initialModelId: NovelChapterModelId;
  /** 만들 화들 중 첫 화의 번호(지금 마지막 화 + 1). */
  firstEpisodeOrdinal: number;
};

/** 확정한 것 — 끝 턴 하나(`batch`) 또는 남은 대화 전부(`chain`), 그 화들을 쓸 모델, 이용자가 본 금액. 모델 선택이
 * 보이지 않는 계정도 요청에는 늘 모델을 싣는다(기본 모델). 금액을 함께 돌려주는 이유는 요청의 `expectedCost` 가 화면에
 * 보인 숫자와 같은 값이어야 해서다. 남은 대화 전부는 견적의 묶음 수를 상한으로 함께 돌려준다. */
export type ChapterBoundaryChoice =
  | { kind: "batch"; endMessageId: string; model: NovelChapterModelId; cost: number }
  | { kind: "chain"; model: NovelChapterModelId; cost: number; maxBatches: number };

const LIST_LABEL = "고를 수 있는 턴";

/** 다음 화들을 어느 턴에서 끝낼지 고르고, 그 자리에서 금액을 확인한다. 고른 턴의 AI 응답 id 와 쓸 모델을 돌려주고,
 * 그만두면 `null` 이다.
 *
 * 금액 확인을 따로 띄우지 않고 여기서 받는 이유: 화 생성은 경계를 확인하는 단계에서 금액을 보이고 동의를 받기로
 * 했다. 고른 직후 같은 화면에 "클로버 N개를 써요"와 잔액이 있으니 실행 버튼이 곧 동의이고, 모달을 하나 더 띄우면
 * 같은 결정을 두 번 묻는다.
 *
 * 모델을 먼저 고른다 — 모델마다 한 번에 담을 수 있는 턴 수가 달라, 후보 목록과 AI 제안, 후보마다의 화 수와 금액이
 * 모델을 따라 바뀐다. 그래서 모델을 바꾸면 그 모델로 제안을 다시 받고, 받는 동안은 고르기·실행을 막는다. 금액은
 * 고른 후보에 서버가 붙인 값 그대로다(화면에서 화 수와 단가를 곱하지 않는다). 소설 상위 모델 허용이 없으면 모델이
 * 하나뿐이라 선택이 그려지지 않는다.
 *
 * "남은 대화 전부"(연쇄)는 같은 목록 맨 위 칸이다 — 어디까지 소설로 만들지라는 같은 질문의 답이고, 모델 → 금액
 * 순서도 같다. 견적은 모델마다 한 번에 받아 두고 고른 모델의 행을 보인다. 남은 대화가 그 모델의 한 묶음 안에 다
 * 들어가면 보이지 않는다(마지막 턴 후보와 같은 일이다). 금액은 견적 그대로이고, 다 만들지 못하면 쓰지 않은 몫을
 * 돌려준다는 것을 칸 안에 말한다.
 *
 * 좁은 화면은 아래 시트, 넓은 화면은 가운데 다이얼로그다 — 둘 중 하나만 마운트한다(포털·포커스 가둠 때문에 공존할
 * 수 없다). 고른 값은 이 컴포넌트가 쥐므로 열린 채 화면 폭이 바뀌어도 남는다. */
export const ChapterBoundaryModal = createCallable<ChapterBoundaryModalProps, ChapterBoundaryChoice | null>(
  ({ call, novelId, proposal: initialProposal, modelOptions, initialModelId, firstEpisodeOrdinal }) => {
    const isDialogLayout = useIsChapterBoundaryDialogLayout();
    const { data: clover } = useCloverBalanceQuery();
    const proposalMutation = useChapterProposalMutation();
    // 열 때마다 새로 받는다 — 대화가 이어지면 남은 대화의 견적이 바뀐다.
    const chainEstimateQuery = useNovelChainEstimateQuery(novelId, true);
    const [proposal, setProposal] = useState(initialProposal);
    const [selectedId, setSelectedId] = useState(() => toInitialChapterEnd(initialProposal));
    const [modelId, setModelId] = useState(initialModelId);
    // 바꾼 모델의 제안을 받는 중인가와 실패 문장. 여러 번 바꾸면 마지막 요청의 응답만 쓴다. 받는 동안 선택·목록을
    // `disabled` 로 잠그지 않는다 — 방금 누른 셀렉트가 비활성이 되면 포커스가 문서 처음으로 떨어진다. 대신 고르기와
    // 실행을 무시하고 실행 버튼을 `aria-disabled` 로 둔다.
    const [isReloading, setIsReloading] = useState(false);
    const [reloadError, setReloadError] = useState<string | undefined>(undefined);
    const latestRequestRef = useRef(0);
    // 고르지 않고 실행을 눌렀을 때의 안내. 한 번 띄우면 고를 때까지 남는다(렌더 때 파생하지 않는다 — 처음 열었을
    // 때부터 "골라주세요" 오류가 떠 있으면 아직 아무것도 안 한 이용자를 탓하는 셈이다).
    const [isSelectionMissing, setIsSelectionMissing] = useState(false);
    const listRef = useRef<HTMLDivElement>(null);
    const errorId = useId();
    const statusId = useId();

    const chainEstimates = toFreshChainEstimates(chainEstimateQuery);
    const chainChoice = toChainChoice(chainEstimates, modelId);
    const isChainSelected = selectedId === CHAIN_CHOICE_VALUE && chainChoice !== undefined;
    const selected = proposal.candidates.find((candidate) => candidate.messageId === selectedId);
    const toRange = (episodeCount: number) =>
      toEpisodeRangeLabel(firstEpisodeOrdinal, firstEpisodeOrdinal + episodeCount - 1);
    const title = `${firstEpisodeOrdinal}화부터 어디까지 담을까요?`;
    const suggestedOrdinal = proposal.candidates.find(
      (candidate) => candidate.messageId === proposal.suggestion?.endMessageId,
    )?.ordinal;
    const description =
      suggestedOrdinal === undefined
        ? "끝낼 턴을 골라주세요. 고른 턴까지의 대화가 분량에 따라 한 화 이상이 돼요."
        : `AI가 ${suggestedOrdinal}번째 턴에서 끊기를 제안했어요. 그대로 두거나 다른 턴을 골라주세요.`;

    async function handleModelChange(next: NovelChapterModelId) {
      if (next === modelId) return;
      const previous = modelId;
      const requestNo = latestRequestRef.current + 1;
      latestRequestRef.current = requestNo;
      setModelId(next);
      setReloadError(undefined);
      setIsReloading(true);
      try {
        const fresh = await proposalMutation.mutateAsync({ novelId, model: next });
        if (requestNo !== latestRequestRef.current) return;
        setProposal(fresh);
        setSelectedId((current) =>
          toSelectionAfterModelChange(current, fresh, toChainChoice(chainEstimates, next) !== undefined),
        );
        setIsSelectionMissing(false);
      } catch (error) {
        if (requestNo !== latestRequestRef.current) return;
        // 받은 후보·금액은 앞 모델의 것이라 모델 선택도 앞 모델로 되돌린다 — 둘이 어긋난 채 실행하면 다른 모델의 금액을
        // 확인받는 셈이다.
        setModelId(previous);
        setReloadError(
          toNovelActionError(error, "proposal")?.message ?? "이 모델의 후보를 받지 못했어요. 잠시 후 다시 시도해주세요.",
        );
      } finally {
        if (requestNo === latestRequestRef.current) setIsReloading(false);
      }
    }

    function handleSelect(value: string) {
      // 단일 토글 그룹은 고른 항목을 다시 누르면 빈 값을 보낸다 — 끝 턴은 늘 하나라 해제를 받지 않는다.
      if (value === "" || isReloading) return;
      setSelectedId(value);
      setIsSelectionMissing(false);
    }

    function handleConfirm() {
      if (isReloading) return;
      if (isChainSelected) {
        call.end({ kind: "chain", model: modelId, cost: chainChoice.cost, maxBatches: chainChoice.batchCount });
        return;
      }
      if (selected === undefined) {
        setIsSelectionMissing(true);
        return;
      }
      call.end({ kind: "batch", endMessageId: selected.messageId, model: modelId, cost: selected.cost });
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
      <div ref={listRef} aria-busy={isReloading} className="flex flex-col gap-1.5">
        <ToggleGroup
          type="single"
          variant="list"
          orientation="vertical"
          value={selectedId ?? ""}
          onValueChange={handleSelect}
          aria-label="화를 끝낼 턴"
          aria-invalid={isSelectionMissing}
          aria-describedby={isSelectionMissing ? errorId : undefined}
          className="w-full"
        >
          {chainChoice !== undefined && (
            <ToggleGroupItem
              value={CHAIN_CHOICE_VALUE}
              className="h-auto w-full flex-col items-start justify-start gap-1 px-3 py-2.5 text-left whitespace-normal hover:bg-secondary"
            >
              <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="font-semibold">남은 대화 전부</span>
                <span className="text-xs font-normal text-muted-foreground tabular-nums">
                  묶음 {chainChoice.batchCount}개 · 최대 {chainChoice.maxEpisodeCount}화 · 최대 클로버{" "}
                  {chainChoice.cost.toLocaleString()}개
                </span>
              </span>
              <span className="text-sm font-normal break-keep text-muted-foreground">
                묶음마다 끝을 AI가 정해요. 묶음 {chainChoice.batchCount}개까지 이어 만들고, 쓰지 않은 클로버는 끝나면
                돌려줘요.
              </span>
            </ToggleGroupItem>
          )}
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
                  <span className="text-xs font-normal text-muted-foreground tabular-nums">
                    {toRange(candidate.episodeCount)}
                  </span>
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

    // 모델 선택과 그 아래 받는 중·실패 줄. 고를 모델이 하나뿐이면 다시 받을 일이 없어 둘 다 그리지 않는다 — 화면이 이
    // 선택이 생기기 전과 같다. 진행 줄은 선택이 있는 동안 늘 마운트된 `aria-live` 다(붙는 순간의 문장을 화면 낭독기가
    // 놓치지 않게). 스피너는 진행 표시라 동작 줄이기 설정에서도 돈다(멈추면 멈춘 화면으로 읽힌다). 실패 문장은 앞
    // 모델로 되돌렸다는 뜻으로 그 자리에 남는다.
    const modelPicker = hasChapterModelChoice(modelOptions) ? (
      <div className="flex flex-col gap-1.5">
        <ChapterModelSelect
          options={modelOptions}
          value={modelId}
          onValueChange={(next) => void handleModelChange(next)}
        />
        <p id={statusId} aria-live="polite" className="text-sm break-keep text-muted-foreground">
          {isReloading && (
            <span className="inline-flex items-center gap-1.5">
              <Loader2 aria-hidden className="size-4 animate-spin" />이 모델로 고를 수 있는 턴을 다시 받는 중이에요.
            </span>
          )}
          {!isReloading && reloadError !== undefined && <span className="text-destructive-text">{reloadError}</span>}
        </p>
      </div>
    ) : null;
    // 금액 줄과 실행 버튼은 고른 칸을 따른다 — 남은 대화 전부면 견적 금액, 턴이면 그 후보의 금액이다.
    const spendCost = isChainSelected ? chainChoice.cost : selected?.cost;
    const summary =
      spendCost === undefined ? (
        <p className="text-sm break-keep text-muted-foreground">끝낼 턴을 고르면 몇 화가 되는지와 금액이 보여요.</p>
      ) : (
        <CloverSpendSummary cost={spendCost} balance={clover?.balance} />
      );
    let confirmLabel = "만들기";
    if (isChainSelected) confirmLabel = "남은 대화 전부 만들기";
    else if (selected !== undefined) confirmLabel = `${toRange(selected.episodeCount)} 만들기`;
    const confirmButtonProps = {
      "aria-disabled": isReloading,
      "aria-describedby": isReloading ? statusId : undefined,
      className: "aria-disabled:opacity-65",
    };

    if (isDialogLayout) {
      return (
        <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
          <DialogContent className="sm:max-w-md" onOpenAutoFocus={focusSelection}>
            <DialogHeader>
              <DialogTitle className="break-keep">{title}</DialogTitle>
              <DialogDescription className="break-keep">{description}</DialogDescription>
            </DialogHeader>
            {modelPicker}
            <DialogBody scrollLabel={LIST_LABEL}>{list}</DialogBody>
            {/* 금액은 목록 밖에 고정한다 — 목록을 내려 읽는 동안에도 누르면 얼마가 빠지는지가 보인다. */}
            {summary}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => call.end(null)}>
                취소
              </Button>
              <Button type="button" {...confirmButtonProps} onClick={handleConfirm}>
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
          {modelPicker !== null && <div className="px-4 pb-4">{modelPicker}</div>}
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
              <Button type="button" {...confirmButtonProps} className="flex-1 aria-disabled:opacity-65" onClick={handleConfirm}>
                {confirmLabel}
              </Button>
            </div>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    );
  },
);
