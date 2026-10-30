import { Button } from "@ai-character-chat/ui/components/button";
import { DialogBody, DialogFooter } from "@ai-character-chat/ui/components/dialog";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link, useRouterState } from "@tanstack/react-router";
import { useId, useLayoutEffect, useRef, useState } from "react";

import { isDefaultChatModel, type ChatModel, type ChatModelId } from "@/entities/chat-model";
import { CloverBalance, isCloverInsufficient, useCloverBalanceQuery } from "@/entities/clover";

import {
  chatModelBadges,
  formatChatModelPrice,
  formatPremiumModelConfirm,
  formatPremiumModelShortage,
} from "../model/chatModelCopy";

type ChatModelOptionsProps = {
  /** 지금 실제로 답을 쓰는 모델. `사용 중` 배지와 처음 선택값이 이것이다. */
  currentModelId: ChatModelId;
  models: ChatModel[];
  /** 목록의 접근 이름 — 무엇의 모델을 고르는지(대화방 / 미리보기)를 말한다. */
  listLabel: string;
  /** 확인 블록의 실행 버튼 글자. */
  commitLabel: string;
  /** 고른 모델을 반영하는 중이면 참 — 목록과 실행 버튼이 눌리지 않는다. */
  isCommitting: boolean;
  /** 이 모델로 바꾸기 전에 확인 블록을 펼칠지. 아니면 누르는 즉시 `onCommit` 이다. */
  needsConfirm: (modelId: ChatModelId) => boolean;
  /** 확인 문장 뒤에 덧붙일 문장. 기본 모델의 확인 블록에서는 이 문장만 보인다. */
  confirmNote?: string;
  /** 클로버 충전 링크 뒤에 덧붙일 문장 — 충전하러 가면 이 화면에서 잃는 것이 있을 때 그 사실을 링크 옆에서 말한다. */
  chargeLinkNote?: string;
  /** 고른 모델을 반영한다. 반영이 실패하면 `cancelConfirm` 을 불러 확인 블록을 거둔다. */
  onCommit: (modelId: ChatModelId, cancelConfirm: () => void) => void;
};

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";

const ITEM_CLASS = "group/model-option h-auto min-h-11 w-full justify-start px-3.5 py-2.5 whitespace-normal hover:bg-secondary";

/** 행 안 보조 글자(가격·`사용 중` 배지)는 행 표면이 한 칸 오르면 잉크도 `foreground` 로 올린다 — 같은 모양의
 * `RoomPersonaPicker` 에서 잰 이유 그대로다(라이트 `muted-foreground` 가 hover·선택 행 위에서 AA 미달). */
const SECONDARY_TEXT_CLASS =
  "text-muted-foreground group-hover/model-option:text-foreground group-data-[state=on]/model-option:text-foreground";

/** 글쓰기 모델 목록과 확인 블록의 화면. 고른 모델을 어디에 반영하는지(대화방 저장 / 미리보기 지역 상태)는 모르고
 * `onCommit` 만 부른다 — 대화방과 미리보기가 같은 목록·같은 확인 문장·같은 접근성 연결을 한 벌로 쓰게 하려는 것이다.
 * 행 순서는 서버 목록 순서 그대로다(서버가 기본 모델을 맨 앞에, 나머지를 턴 가격 오름차순으로 준다).
 *
 * 기본 모델이 아닌 모델의 확인 블록은 클로버 사용 동의다: 그 모델은 단가가 더 높고, 바꾼 뒤에는 턴마다 따로 묻지 않아
 * 이 확인이 그 단가를 묻는 유일한 자리다. 그래서 확인 문장·잔액·부족 안내는 기본 모델이 아닌 모델에만 붙는다. 기본
 * 모델인지는 서버 목록의 기본 모델 표시로 정한다(모델 id 를 손으로 적지 않는다).
 *
 * 다이얼로그의 본문(목록)과 푸터(확인 블록)를 함께 돌려준다 — 호출부는 `DialogHeader` 뒤에 이것만 둔다. 확인 블록은
 * 모달 위 모달이 아니라 푸터에 펼친다: 고른 행이 틴트로 남아 무엇을 확인하는지가 같은 화면에 보이고, 모델이 많아 목록이
 * 길어도 본문만 스크롤해 확인 블록이 화면 밖으로 밀리지 않는다. 실행 버튼만 `primary` 솔리드다(목록은 `variant="list"`
 * 틴트, DESIGN.md Toggles 절). */
export function ChatModelOptions({
  currentModelId,
  models,
  listLabel,
  commitLabel,
  isCommitting,
  needsConfirm,
  confirmNote,
  chargeLinkNote,
  onCommit,
}: ChatModelOptionsProps) {
  const { data: clover } = useCloverBalanceQuery();
  // 충전하고 돌아올 곳. 충전 화면이 이 주소로 "돌아가기"를 두고, 결제창·로그인 왕복 뒤에도 잃지 않게 넘겨 다닌다.
  const returnTo = useRouterState({ select: (state) => state.location.href });
  const [pendingModelId, setPendingModelId] = useState<ChatModelId | undefined>(undefined);
  const confirmId = useId();
  const shortageId = useId();
  const pendingModel = models.find((model) => model.id === pendingModelId);
  // 확인 문장·잔액·부족 안내는 고른 모델이 기본 모델이 아닐 때만 붙는다.
  const pendingPremiumModel =
    pendingModel && isDefaultChatModel(models, pendingModel.id) === false ? pendingModel : undefined;
  const isPendingModelShort =
    pendingPremiumModel !== undefined &&
    clover !== undefined &&
    isCloverInsufficient(clover.balance, pendingPremiumModel.turnCost);
  const listRef = useRef<HTMLDivElement>(null);
  const pendingDescriptionIds = isPendingModelShort ? `${confirmId} ${shortageId}` : confirmId;
  // 상위 모델이면 확인 문장이 먼저, 덧붙일 문장이 그 뒤다. 한 문단의 한 글자열로 이어 읽힌다.
  const confirmText = [pendingPremiumModel && formatPremiumModelConfirm(pendingPremiumModel), confirmNote]
    .filter((sentence) => sentence !== undefined)
    .join(" ");

  // 푸터가 나타나면 본문이 그만큼 줄어 목록 아래쪽에서 고른 행이 가려질 수 있다 — 칠하기 전에 그 행을 본문 안으로
  // 들인다. 움직임 없이 바로 옮긴다(이미 보이면 그대로다). 포커스는 행에 남는다.
  useLayoutEffect(() => {
    if (pendingModelId === undefined) return;
    listRef.current?.querySelector('[data-state="on"]')?.scrollIntoView({ block: "nearest" });
  }, [pendingModelId]);

  function cancelConfirm() {
    setPendingModelId(undefined);
  }

  function handleValueChange(value: string) {
    // 고른 항목을 다시 누르면 Radix 가 "" 를 보낸다 — 선택은 언제나 하나라 무시한다.
    if (value === "" || isCommitting) return;
    const model = models.find((item) => item.id === value);
    if (!model) return;
    if (model.id === currentModelId) {
      setPendingModelId(undefined);
      return;
    }
    if (needsConfirm(model.id)) {
      setPendingModelId(model.id);
      return;
    }
    setPendingModelId(undefined);
    onCommit(model.id, cancelConfirm);
  }

  function handleConfirm() {
    if (isCommitting || pendingModelId === undefined) return;
    onCommit(pendingModelId, cancelConfirm);
  }

  return (
    <>
      <DialogBody>
        <ToggleGroup
          ref={listRef}
          type="single"
          variant="list"
          orientation="vertical"
          value={pendingModelId ?? currentModelId}
          onValueChange={handleValueChange}
          aria-label={listLabel}
          aria-busy={isCommitting}
          className="w-full flex-col gap-1.5"
        >
          {models.map((model) => (
            <ToggleGroupItem
              key={model.id}
              value={model.id}
              aria-describedby={model.id === pendingModelId ? pendingDescriptionIds : undefined}
              className={ITEM_CLASS}
            >
              <span className="flex min-w-0 flex-col gap-0.5 text-left">
                {/* 배지 둘(`베타`·`사용 중`)이 붙어도 이름을 자르지 않게 줄을 넘긴다 — 배지가 다음 줄로 내려간다. */}
                <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="min-w-0 text-sm font-medium break-keep wrap-break-word text-foreground">{model.name}</span>
                  {chatModelBadges(model, currentModelId).map((badge) => (
                    <span
                      key={badge}
                      className={cn(
                        "inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium",
                        SECONDARY_TEXT_CLASS,
                      )}
                    >
                      {badge}
                    </span>
                  ))}
                </span>
                <span className={cn("text-xs break-keep", SECONDARY_TEXT_CLASS)}>{formatChatModelPrice(model)}</span>
              </span>
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </DialogBody>

      {/* 확인이 걸렸을 때만 푸터가 생긴다. 좁은 화면에서도 문장·안내·버튼 줄을 세로로 쌓고, 버튼 줄은 직접 가로로 둔다
          (`DialogFooter` 는 좁은 화면에서 자식을 세로로 쌓는다). 잔액은 버튼 줄 왼쪽에 둬 푸터 높이를 줄인다. */}
      {pendingModel && (
        <DialogFooter className="gap-3 sm:flex-col sm:justify-start">
          <p id={confirmId} className="text-sm break-keep text-foreground">
            {confirmText}
          </p>
          {/* 부족해도 바꾸는 것은 막지 않는다(전송할 때 서버가 판정한다). 충전으로 가는 길은 텍스트 링크다 — 이 블록의
              솔리드 채움은 실행 버튼 하나뿐이어야 한다. */}
          {pendingPremiumModel && isPendingModelShort && (
            <p id={shortageId} className="text-sm break-keep text-foreground">
              {formatPremiumModelShortage(pendingPremiumModel)}{" "}
              <Link to="/clover" search={{ returnTo }} className={INLINE_LINK_CLASS}>
                클로버 충전하기
              </Link>
              {chargeLinkNote !== undefined && ` ${chargeLinkNote}`}
            </p>
          )}
          {/* 잔액과 버튼 둘이 한 줄에 다 들어가지 않으면(좁은 화면의 긴 실행 버튼 글자) 버튼 둘을 묶음째 다음 줄로
              넘긴다 — 버튼 하나만 넘어가 둘이 갈라지지 않게. */}
          <div className="flex flex-wrap items-center justify-end gap-2">
            {pendingPremiumModel && clover && (
              <p className="mr-auto flex items-center gap-1.5 text-sm text-muted-foreground">
                <span>남은 클로버</span>
                <CloverBalance balance={clover.balance} />
              </p>
            )}
            {/* 버튼 순서는 `취소` 먼저 — 확인 모달 푸터와 같다. 반영 중에는 실행을 `disabled` 대신 `aria-disabled` 로
                막아 누른 버튼에서 포커스가 빠지지 않게 한다. */}
            <div className="ml-auto flex gap-2">
              <Button type="button" variant="outline" onClick={cancelConfirm}>
                취소
              </Button>
              <Button
                type="button"
                aria-disabled={isCommitting}
                className="aria-disabled:opacity-65"
                onClick={handleConfirm}
              >
                {commitLabel}
              </Button>
            </div>
          </div>
        </DialogFooter>
      )}
    </>
  );
}
