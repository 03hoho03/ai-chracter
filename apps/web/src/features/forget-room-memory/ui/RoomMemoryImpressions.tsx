import { useId, useState } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown, CircleSlash, Info } from "lucide-react";

import { useChatRoomMemoryItemsQuery, type ChatRoomMemoryImpression } from "@/entities/chat-room";

import { impressionSourceLabel, turnRangeLabel } from "../model/memoryItemText";
import { MemoryItemsEmpty } from "./MemoryItemsParts";
import { MemoryNote } from "./MemoryNote";

/** 노트·요약 탭의 요약 아래에 놓이는 관계 인상 구획. 장면·사실 탭과 같은 목록 응답을 쓴다. 받는 동안이나 받지 못했으면 아무것도
 * 그리지 않는다 — 대부분의 방은 서버가 인상 칸을 비워 보내 구획이 없으므로, 자리표시를 띄웠다 거두면 요약 아래가 한 번
 * 출렁일 뿐이다. 불러오기 실패와 다시 시도는 장면·사실 탭이 맡는다. */
export function RoomMemoryImpressions({ roomId }: { roomId: string }) {
  const itemsQuery = useChatRoomMemoryItemsQuery(roomId);
  return <MemoryImpressionsSection impressions={itemsQuery.data?.impressions} />;
}

/** 이전 인상의 펼침은 이 구획의 상태다 — 탭을 오가도 노트·요약 탭이 마운트된 채라 남고, 패널을 닫으면 접힌 채로 돌아온다. */
export function MemoryImpressionsSection({ impressions }: { impressions: ChatRoomMemoryImpression[] | undefined }) {
  const [isOlderOpen, setIsOlderOpen] = useState(false);

  if (!impressions) return null;
  return (
    <MemoryImpressionsView
      impressions={impressions}
      isOlderOpen={isOlderOpen}
      onToggleOlder={() => setIsOlderOpen((open) => !open)}
    />
  );
}

type MemoryImpressionsViewProps = {
  impressions: ChatRoomMemoryImpression[];
  isOlderOpen: boolean;
  onToggleOlder: () => void;
};

/** 가장 최근 인상 하나는 줄이지 않고 전문으로 보이고, 이전 것은 버튼 하나 아래에 접는다. 펼침은 즉시 바뀐다(본문을 `hidden`
 * 으로 숨겨 높이 전이를 걸 수 없고, 어두운 방에서 갑작스러운 움직임은 놀람이라 셰브런 회전에도 전이를 두지 않는다). 버튼은
 * 펼쳐도 같은 자리의 같은 요소라 포커스가 그대로 남는다. 잊게 하기 버튼은 없다 — 근거 장면이나 사실을 잊게 하면 함께 지워진다. */
export function MemoryImpressionsView({ impressions, isOlderOpen, onToggleOlder }: MemoryImpressionsViewProps) {
  const headingId = useId();
  const olderListId = useId();
  const [latest, ...older] = impressions;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 border-t border-border pt-5">
      <h3 id={headingId} className="text-sm font-semibold text-foreground">
        관계의 인상
      </h3>
      <MemoryNote icon={CircleSlash}>캐릭터의 응답에는 쓰이지 않아요. 이 방을 돌아보는 기록이에요.</MemoryNote>

      {latest === undefined ? (
        <MemoryItemsEmpty>아직 쌓인 인상이 없어요. 대화가 쌓이면 이 방의 관계 흐름이 여기에 정리돼요.</MemoryItemsEmpty>
      ) : (
        <>
          <ImpressionEntry impression={latest} />
          {older.length > 0 && (
            <div className="flex flex-col">
              <button
                type="button"
                aria-expanded={isOlderOpen}
                aria-controls={olderListId}
                onClick={onToggleOlder}
                className="inline-flex min-h-8 items-center gap-1 self-start rounded-sm text-sm font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-10"
              >
                {isOlderOpen ? "이전 인상 접기" : `이전 인상 ${older.length}개`}
                <ChevronDown aria-hidden className={cn("size-4 shrink-0", isOlderOpen && "rotate-180")} />
              </button>
              <ul id={olderListId} hidden={!isOlderOpen} className="flex flex-col">
                {older.map((impression) => (
                  <li key={impression.id} className="border-b border-border py-3 first:pt-2 last:border-b-0">
                    <ImpressionEntry impression={impression} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          <MemoryNote icon={Info}>근거가 된 장면이나 사실을 잊게 하면 그 인상도 함께 지워져요.</MemoryNote>
        </>
      )}
    </section>
  );
}

function ImpressionEntry({ impression }: { impression: ChatRoomMemoryImpression }) {
  const { turnStart, turnEnd } = impression;
  const turnLabel = turnStart !== undefined && turnEnd !== undefined ? turnRangeLabel(turnStart, turnEnd) : undefined;
  const sourceLabel = impressionSourceLabel(impression.sceneCount, impression.factCount);

  return (
    <div className="flex flex-col gap-1">
      {(turnLabel || sourceLabel) && (
        <p className="flex flex-wrap gap-x-2 text-xs text-muted-foreground tabular-nums">
          {turnLabel && <span>{turnLabel}</span>}
          {sourceLabel && <span>{sourceLabel}</span>}
        </p>
      )}
      <p className="text-sm break-keep wrap-break-word text-pretty text-foreground">{impression.text}</p>
    </div>
  );
}
