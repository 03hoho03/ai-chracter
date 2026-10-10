import { Button } from "@ai-character-chat/ui/components/button";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { toast } from "sonner";

import { isPremiumChatModel, type ChatModel, type ChatModelId } from "@/entities/chat-model";
import { CloverBalance, isCloverInsufficient, useCloverBalanceQuery } from "@/entities/clover";
import { useSessionQuery } from "@/entities/session";

import { useSetRoomChatModelMutation } from "../api/useSetRoomChatModelMutation";
import { isChatModelNotAllowedError } from "../model/chatModelError";
import {
  chatModelBadges,
  formatChatModelPrice,
  formatPremiumModelConfirm,
  formatPremiumModelShortage,
} from "../model/chatModelCopy";

type ChatModelPickerProps = {
  roomId: string;
  /** 방이 지금 실제로 쓰는 모델(유효 모델). 저장한 상위 모델을 쓸 수 없게 되면 서버가 기본 모델로 알려 준다. */
  currentModelId: ChatModelId;
  models: ChatModel[];
  onChanged: () => void;
};

const INLINE_LINK_CLASS = "font-medium whitespace-nowrap text-primary underline-offset-4 hover:underline focus-visible:underline";

const ITEM_CLASS = "group/model-option h-auto min-h-11 w-full justify-start px-3.5 py-2.5 whitespace-normal hover:bg-secondary";

/** 행 안 보조 글자(가격·`사용 중` 배지)는 행 표면이 한 칸 오르면 잉크도 `foreground` 로 올린다 — 같은 모양의
 * `RoomPersonaPicker` 에서 잰 이유 그대로다(라이트 `muted-foreground` 가 hover·선택 행 위에서 AA 미달). */
const SECONDARY_TEXT_CLASS =
  "text-muted-foreground group-hover/model-option:text-foreground group-data-[state=on]/model-option:text-foreground";

/** 대화방의 글쓰기 모델 목록. 기본 모델로는 누르면 바로 바꾸고, 상위 모델은 고른 뒤 한 번 더 확인받는다.
 *
 * 상위 모델에만 확인을 두는 이유: 그 모델은 무료 대화 없이 턴마다 클로버를 쓰고, 바꾼 뒤에는 하루 한 번 확인도 묻지
 * 않는다 — 이 확인이 그 방에서 클로버를 쓰겠다는 유일한 동의다. 기본 모델로 되돌리는 것은 돈이 덜 드는 쪽이라 묻지
 * 않는다(허용을 거둔 뒤에도 되돌릴 수 있다).
 *
 * 확인은 모달 위 모달이 아니라 목록 아래에 펼친다 — 고른 행이 틴트로 남아 무엇을 확인하는지가 같은 화면에 보인다.
 * 실행 버튼만 `primary` 솔리드다(목록은 `variant="list"` 틴트, DESIGN.md Toggles 절). */
export function ChatModelPicker({ roomId, currentModelId, models, onChanged }: ChatModelPickerProps) {
  const setRoomChatModelMutation = useSetRoomChatModelMutation(roomId);
  const { data: clover } = useCloverBalanceQuery();
  const { data: me } = useSessionQuery();
  const [pendingModelId, setPendingModelId] = useState<ChatModelId | undefined>(undefined);
  const confirmId = useId();
  const shortageId = useId();
  const pendingModel = models.find((model) => model.id === pendingModelId);
  const isPendingModelShort =
    pendingModel !== undefined && clover !== undefined && isCloverInsufficient(clover.balance, pendingModel.turnCost);
  const pendingDescriptionIds = isPendingModelShort ? `${confirmId} ${shortageId}` : confirmId;
  const isSaving = setRoomChatModelMutation.isPending;

  function save(modelId: ChatModelId) {
    setRoomChatModelMutation.mutate(modelId, {
      onSuccess: () => {
        toast.success("모델을 바꿨어요. 다음 턴부터 적용돼요.");
        onChanged();
      },
      onError: (error) => {
        setPendingModelId(undefined);
        toast.error(
          isChatModelNotAllowedError(error)
            ? "이 모델을 지금 이 계정에서 쓸 수 없어요."
            : "모델을 바꾸지 못했어요. 잠시 후 다시 시도해주세요.",
        );
      },
    });
  }

  function handleValueChange(value: string) {
    // 고른 항목을 다시 누르면 Radix 가 "" 를 보낸다 — 선택은 언제나 하나라 무시한다.
    if (value === "" || isSaving) return;
    const model = models.find((item) => item.id === value);
    if (!model) return;
    if (model.id === currentModelId) {
      setPendingModelId(undefined);
      return;
    }
    if (isPremiumChatModel(model.id)) {
      setPendingModelId(model.id);
      return;
    }
    setPendingModelId(undefined);
    save(model.id);
  }

  function handleConfirm() {
    if (isSaving || pendingModelId === undefined) return;
    save(pendingModelId);
  }

  return (
    <div className="flex flex-col gap-4">
      <ToggleGroup
        type="single"
        variant="list"
        orientation="vertical"
        value={pendingModelId ?? currentModelId}
        onValueChange={handleValueChange}
        aria-label="이 대화방의 글쓰기 모델"
        aria-busy={isSaving}
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
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-medium text-foreground">{model.name}</span>
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
              <span className={cn("text-xs break-keep", SECONDARY_TEXT_CLASS)}>{formatChatModelPrice(model, me?.identityGated ?? false)}</span>
            </span>
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {pendingModel && (
        <div className="flex flex-col gap-3 border-t border-border pt-4">
          <p id={confirmId} className="text-sm break-keep text-foreground">
            {formatPremiumModelConfirm(pendingModel)}
          </p>
          {clover && (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <span>남은 클로버</span>
              <CloverBalance balance={clover.balance} />
            </p>
          )}
          {/* 부족해도 바꾸는 것은 막지 않는다(전송할 때 서버가 판정한다). 충전으로 가는 길은 텍스트 링크다 — 이 블록의
              솔리드 채움은 실행 버튼 하나뿐이어야 한다. */}
          {isPendingModelShort && (
            <p id={shortageId} className="text-sm break-keep text-foreground">
              {formatPremiumModelShortage(pendingModel)}{" "}
              <Link to="/clover" className={INLINE_LINK_CLASS}>
                클로버 충전하기
              </Link>
            </p>
          )}
          {/* 버튼 순서는 `취소` 먼저 — 확인 모달 푸터와 같다. 저장 중에는 실행을 `disabled` 대신 `aria-disabled` 로
              막아 누른 버튼에서 포커스가 빠지지 않게 한다. */}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setPendingModelId(undefined)}>
              취소
            </Button>
            <Button
              type="button"
              aria-disabled={isSaving}
              className="aria-disabled:opacity-65"
              onClick={handleConfirm}
            >
              이 모델로 바꾸기
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
