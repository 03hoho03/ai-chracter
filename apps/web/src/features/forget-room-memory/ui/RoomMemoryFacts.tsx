import { useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, useChatRoomMemoryItemsQuery, type ChatRoomMemoryFact } from "@/entities/chat-room";

import { factHeading } from "../model/memoryItemText";
import { FactSummary } from "./FactSummary";
import { ForgetButton } from "./ForgetButton";
import { ForgetFactModal } from "./ForgetFactModal";
import {
  ForgetResultNotice,
  MemoryComebackNote,
  MemoryItemsEmpty,
  MemoryItemsLoadError,
  MemoryItemsSkeleton,
  UsedInRepliesLine,
} from "./MemoryItemsParts";
import { useForgetResultNotice } from "./useForgetResultNotice";

type RoomMemoryFactsProps = {
  roomId: string;
  /** 잊은 뒤 알림의 "요약 고치기" — 요약 편집은 다른 탭(다른 feature)이라 위젯이 탭을 옮기고 편집을 연다. */
  onEditSummaryRequest: () => void;
};

/** 방의 사실 기억 목록. 키마다 지금 이긴 사실 하나씩이고 페이지가 없다(장면 목록과 같은 응답에 전부 온다). */
export function RoomMemoryFacts({ roomId, onEditSummaryRequest }: RoomMemoryFactsProps) {
  const queryClient = useQueryClient();
  const itemsQuery = useChatRoomMemoryItemsQuery(roomId);
  const { notice, noticeRef, showOutcome } = useForgetResultNotice();

  if (itemsQuery.isPending) return <MemoryItemsSkeleton />;
  if (!itemsQuery.data) {
    return <MemoryItemsLoadError onRetry={() => void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) })} />;
  }

  const { facts, factsUsedInReplies } = itemsQuery.data;

  async function handleForget(fact: ChatRoomMemoryFact) {
    showOutcome(await ForgetFactModal.call({ roomId, fact }), factHeading(fact));
  }

  return (
    <div className="flex flex-col gap-3">
      {notice && <ForgetResultNotice ref={noticeRef} notice={notice} onEditSummaryRequest={onEditSummaryRequest} />}
      <UsedInRepliesLine kind="facts" isUsed={factsUsedInReplies} />

      {facts.length === 0 ? (
        <MemoryItemsEmpty>아직 사실 기억이 없어요. 대화가 쌓여 요약에 정리되면 그 구간의 사실이 여기 보여요.</MemoryItemsEmpty>
      ) : (
        <ul className="flex flex-col">
          {facts.map((fact) => (
            <li key={fact.id} className="flex items-start gap-2 border-b border-border py-3 last:border-b-0">
              <FactSummary fact={fact} className="flex-1" />
              <ForgetButton label={`‘${factHeading(fact)}’ 잊게 하기`} onClick={() => void handleForget(fact)} />
            </li>
          ))}
        </ul>
      )}

      <MemoryComebackNote />
    </div>
  );
}
