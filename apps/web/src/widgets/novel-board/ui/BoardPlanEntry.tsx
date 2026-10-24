import { Button } from "@ai-character-chat/ui/components/button";
import { useId } from "react";

import { useNovelOutlineQuery, useNovelSourceSelectionQuery, type NovelDetailResponse } from "@/entities/novel";
import { OUTLINE_STATUS_LABEL, toManuscriptProgressLine, toOutlineBase } from "@/features/plan-novel-outline";
import { SOURCE_SELECTION_STATUS_LABEL, hasChangedSource, toSourceSelectionStatus } from "@/features/select-novel-source";

type BoardPlanEntryProps = {
  novel: NovelDetailResponse;
  onOpen: () => void;
};

/**
 * 보드 개요(넓은 화면)·목록(좁은 화면)의 구성 화면 입구 — 단계 상태 한 줄과 "구성 열기". 구성 흐름 스위치가 켜졌을 때만
 * 호출부가 그린다. 대화방이 지워진 소설도 이 입구로 들어온다(상단바 "다음 화 만들기"가 막혀 있다) — 그때는 담을 대화를 묻지
 * 않는다(서버가 409 로 막는다).
 *
 * 버튼의 `data-board-key` 는 구성 모드를 닫은 뒤 보드가 포커스를 돌려줄 자리다.
 */
export function BoardPlanEntry({ novel, onOpen }: BoardPlanEntryProps) {
  const headingId = useId();
  const isRoomGone = novel.chatRoomId === null;
  const query = useNovelSourceSelectionQuery(novel.id, { enabled: !isRoomGone });
  const outlineQuery = useNovelOutlineQuery(novel.id, { enabled: true });
  const outlineLine = toOutlineLine(outlineQuery.data === undefined ? undefined : toOutlineBase(outlineQuery.data));
  // 승인한 구성안이 있으면 셋째 단계(화별 장면·원고)의 원고 수를 한 줄 더한다.
  const approvedEpisodes = outlineQuery.data?.approved?.episodes;
  const manuscriptLine = approvedEpisodes === undefined ? undefined : toManuscriptProgressLine(approvedEpisodes);

  return (
    <section aria-labelledby={headingId} className="flex flex-col items-start gap-2 rounded-xl border border-border p-4">
      <h3 id={headingId} className="text-sm font-semibold text-foreground">
        구성
      </h3>
      <p className="text-sm break-keep text-muted-foreground">{toStatusLine(isRoomGone, query)}</p>
      {outlineLine !== undefined && <p className="text-sm break-keep text-muted-foreground">{outlineLine}</p>}
      {manuscriptLine !== undefined && <p className="text-sm break-keep text-muted-foreground">{manuscriptLine}</p>}
      <Button type="button" variant="outline" size="sm" data-board-key="plan" onClick={onOpen}>
        구성 열기
      </Button>
    </section>
  );
}

function toStatusLine(isRoomGone: boolean, query: ReturnType<typeof useNovelSourceSelectionQuery>): string {
  if (isRoomGone) return "원래 대화방이 지워져 담을 대화를 새로 고를 수 없어요.";
  if (query.data === undefined) {
    return query.isError ? "담을 대화 상태를 불러오지 못했어요." : "담을 대화를 확인하는 중이에요.";
  }
  const status = SOURCE_SELECTION_STATUS_LABEL[toSourceSelectionStatus(query.data)];
  const latest = query.data.draft ?? query.data.approved;
  const changed = latest !== null && hasChangedSource(latest) ? " · 원문 바뀜" : "";
  return `담을 대화 · ${status}${changed}`;
}

/** 전체 구성안 상태 한 줄. 구성안이 아직 없거나(받는 중·못 받음 포함) 모르면 줄을 두지 않는다 — 담을 대화 줄이 다음 할 일을 말한다. */
function toOutlineLine(base: ReturnType<typeof toOutlineBase> | undefined): string | undefined {
  if (base === undefined) return undefined;
  return `전체 구성안 · ${OUTLINE_STATUS_LABEL[base.status]}${base.isStale ? " · 낡음" : ""}`;
}
