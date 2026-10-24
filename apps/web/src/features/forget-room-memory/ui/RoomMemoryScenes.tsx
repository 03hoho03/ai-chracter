import { useState } from "react";
import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

import { chatRoomKeys, useChatRoomMemoryItemsQuery, type ChatRoomMemoryEpisode } from "@/entities/chat-room";

import { turnRangeLabel } from "../model/memoryItemText";
import { ForgetButton } from "./ForgetButton";
import { ForgetSceneModal } from "./ForgetSceneModal";
import { MEMORY_BADGE_CLASS } from "./memoryBadge";
import {
  ForgetResultNotice,
  MemoryComebackNote,
  MemoryItemsEmpty,
  MemoryItemsLoadError,
  MemoryItemsSkeleton,
  UsedInRepliesLine,
} from "./MemoryItemsParts";
import { useForgetResultNotice } from "./useForgetResultNotice";

type RoomMemoryScenesProps = {
  roomId: string;
  /** 잊은 뒤 알림의 "요약 고치기" — 요약 편집은 다른 탭(다른 feature)이라 위젯이 탭을 옮기고 편집을 연다. */
  onEditSummaryRequest: () => void;
};

/** 방의 장면 기억 목록. 30개씩 "더 보기"로 이어 받는다. 행마다 지우개 버튼이 잊게 하기 확인을 연다. */
export function RoomMemoryScenes({ roomId, onEditSummaryRequest }: RoomMemoryScenesProps) {
  const queryClient = useQueryClient();
  const itemsQuery = useChatRoomMemoryItemsQuery(roomId);
  const { notice, noticeRef, showOutcome } = useForgetResultNotice();

  if (itemsQuery.isPending) return <MemoryItemsSkeleton />;
  if (!itemsQuery.data) {
    // 기억 응답까지 다시 받는다 — 스위치가 꺼져 목록이 404 였다면 패널이 목록 없는 모양으로 돌아간다(목록 키가 그 아래다).
    return <MemoryItemsLoadError onRetry={() => void queryClient.invalidateQueries({ queryKey: chatRoomKeys.memory(roomId) })} />;
  }

  const { episodes, hasMoreEpisodes, episodesUsedInReplies } = itemsQuery.data;
  const hasCharacterOnly = episodes.some((episode) => episode.assertedBy === "character");
  const isLoadingMore = itemsQuery.isFetchingNextPage;

  async function handleForget(episode: ChatRoomMemoryEpisode) {
    showOutcome(await ForgetSceneModal.call({ roomId, episode }), episode.title);
  }

  return (
    <div className="flex flex-col gap-3">
      {notice && <ForgetResultNotice ref={noticeRef} notice={notice} onEditSummaryRequest={onEditSummaryRequest} />}
      <UsedInRepliesLine kind="episodes" isUsed={episodesUsedInReplies} />

      {episodes.length === 0 ? (
        <MemoryItemsEmpty>아직 장면 기억이 없어요. 대화가 쌓여 요약에 정리되면 그 구간의 장면이 여기 보여요.</MemoryItemsEmpty>
      ) : (
        <>
          {hasCharacterOnly && (
            <p className="text-xs break-keep text-muted-foreground">
              &lsquo;캐릭터 말로만&rsquo;은 캐릭터가 대사로만 꺼낸 장면이라 응답에서 다시 떠올리지 않아요.
            </p>
          )}
          <ul className="flex flex-col">
            {episodes.map((episode) => (
              <SceneRow key={episode.id} episode={episode} onForget={() => void handleForget(episode)} />
            ))}
          </ul>
        </>
      )}

      {hasMoreEpisodes && (
        <Button
          type="button"
          variant="outline"
          aria-disabled={isLoadingMore}
          className="w-full hover:bg-secondary aria-disabled:opacity-65"
          onClick={() => {
            if (!isLoadingMore) void itemsQuery.fetchNextPage();
          }}
        >
          {isLoadingMore ? "불러오는 중…" : "장면 더 보기"}
        </Button>
      )}
      {itemsQuery.isFetchNextPageError && (
        <p role="alert" className="text-xs break-keep text-destructive-text">
          장면을 더 불러오지 못했어요. 다시 눌러 주세요.
        </p>
      )}

      <MemoryComebackNote />
    </div>
  );
}

function SceneRow({ episode, onForget }: { episode: ChatRoomMemoryEpisode; onForget: () => void }) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <li className="flex items-start gap-2 border-b border-border py-3 last:border-b-0">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-sm font-semibold break-keep wrap-break-word text-foreground">{episode.title}</span>
        {/* 목록에서는 두 줄로 줄이고 누르면 전문을 편다 — 작은 화면에 장면을 더 담으면서 내용 전체를 볼 수 있게. 스크린리더는
            줄인 상태에서도 전문을 읽는다(줄임은 그리기만 자른다). */}
        <button
          type="button"
          aria-expanded={isExpanded}
          onClick={() => setIsExpanded((expanded) => !expanded)}
          className="rounded-sm text-left text-sm break-keep wrap-break-word text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className={cn(!isExpanded && "line-clamp-2")}>{episode.detail}</span>
        </button>
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span className="tabular-nums">{turnRangeLabel(episode.startTurn, episode.endTurn)}</span>
          {episode.assertedBy === "character" && <span className={MEMORY_BADGE_CLASS}>캐릭터 말로만</span>}
        </span>
      </div>
      <ForgetButton label={`‘${episode.title}’ 잊게 하기`} onClick={onForget} />
    </li>
  );
}
