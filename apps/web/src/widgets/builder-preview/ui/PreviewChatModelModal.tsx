import type { ReactNode } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";

import { useChatModelsQuery, type ChatModelId } from "@/entities/chat-model";
import { ChatModelOptions } from "@/features/select-chat-model";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { previewModelNeedsConfirm } from "../model/previewChatModel";

type PreviewChatModelModalProps = {
  /** 미리보기가 지금 실제로 답을 쓰는 모델. */
  currentModelId: ChatModelId;
  /** 서버에 미리보기 세션이 이미 열려 있는가 — 있으면 모델을 바꾸는 것이 곧 처음부터 다시 시작하는 것이다. */
  hasSession: boolean;
};

/** 세션이 있을 때 확인 블록에만 둔다 — 다이얼로그 설명에도 두면 한 모달에 같은 문장이 두 번 보이고 낭독기도 두 번 읽는다.
 * "바꾸면"으로 시작하지 않는 것은 상위 모델 확인 문장(대화방과 같은 문장이라 고치지 않는다)의 "바꾸면 …" 바로 뒤에 붙기 때문이다. */
const RESTART_NOTE = "지금 미리보기 대화는 처음부터 다시 시작돼요.";

/** 충전 링크는 같은 탭에서 빌더를 떠난다. 초안은 떠날 때 저장되지만 미리보기 대화는 화면에만 있어 사라진다. */
const CHARGE_LINK_NOTE = "충전하러 가면 미리보기 대화는 사라져요(초안은 저장돼요).";

/** 빌더 미리보기의 글쓰기 모델 선택. 고른 모델을 돌려줄 뿐 저장하지 않는다 — 미리보기의 모델은 그 화면의 지역 상태이고,
 * 세션을 다시 여는 일은 부른 쪽이 한다. 닫거나 취소하면 undefined 다.
 *
 * 목록과 확인 블록은 대화방 모델 선택과 같은 `ChatModelOptions` 다 — 작가가 미리보기에서 고르는 것과 독자가 대화방에서
 * 고르는 것이 같은 목록·같은 확인 문장이어야 한다(미리보기 상위 모델 턴도 같은 방식으로 첫 턴부터 차감된다). 목록은 열 때마다
 * 서버에 다시 묻는다(상위 모델 허용은 세션 중에도 바뀐다). */
export const PreviewChatModelModal = createCallable<PreviewChatModelModalProps, ChatModelId | undefined>(
  ({ call, currentModelId, hasSession }) => {
    const modelsQuery = useChatModelsQuery();
    const models = modelsQuery.data;

    // 세 상태(불러오는 중·실패·목록)는 배타적이다 — 렌더 전에 한 갈래로 정한다(대화방 모델 모달과 같은 갈래).
    let body: ReactNode;
    if (modelsQuery.isPending) {
      body = <p className="py-6 text-center text-sm text-muted-foreground">불러오는 중…</p>;
    } else if (!models) {
      body = (
        <div className="flex flex-col items-center gap-3 py-6">
          <p className="text-sm break-keep text-muted-foreground">모델 목록을 불러오지 못했어요.</p>
          <Button type="button" variant="outline" onClick={() => void modelsQuery.refetch()}>
            다시 시도
          </Button>
        </div>
      );
    } else {
      body = (
        <ChatModelOptions
          currentModelId={currentModelId}
          models={models}
          listLabel="이 미리보기의 글쓰기 모델"
          commitLabel={hasSession ? "바꾸고 처음부터 시작" : "이 모델로 바꾸기"}
          isCommitting={false}
          needsConfirm={(modelId) => previewModelNeedsConfirm(modelId, hasSession)}
          confirmNote={hasSession ? RESTART_NOTE : undefined}
          chargeLinkNote={CHARGE_LINK_NOTE}
          onCommit={(modelId) => call.end(modelId)}
        />
      );
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(undefined)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>AI 모델</DialogTitle>
            <DialogDescription className="break-keep">
              이 미리보기에서 캐릭터의 답을 쓰는 모델이에요. 모델마다 문체가 달라 답의 느낌이 바뀔 수 있어요.
            </DialogDescription>
          </DialogHeader>

          <DialogBody>{body}</DialogBody>
        </DialogContent>
      </Dialog>
    );
  },
);
