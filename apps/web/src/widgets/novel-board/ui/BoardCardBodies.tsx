import { cn } from "@ai-character-chat/ui/lib/utils";
import { CircleCheck, Loader2, NotebookPen, Sparkles, UserRound } from "lucide-react";

import type { CharacterNodeData, EpisodeNodeData, NotesNodeData } from "../model/boardNode";

/**
 * 카드 껍데기. 카드 전체가 고르는 버튼 노릇을 하는 클릭 카드라 button-outline 레시피다(`bg-background` +
 * `hover:bg-muted`, 그림자 없음). 캔버스 카드와 좁은 화면의 목록 행이 같은 껍데기·같은 내용을 쓴다 — 두 배치가
 * 같은 데이터의 두 모습이라서. 목록 행은 `<button>` 이라 내용은 전부 구문 요소(`span`)로 짠다.
 *
 * 고른 카드는 강조색 테두리 두 겹(`border` + 안쪽 링 1px)이다 — 테두리 두께를 바꾸면 안의 글이 1px 밀린다. 키보드
 * 포커스는 그 바깥의 반투명 링이라, 고름과 포커스가 겹쳐도 둘 다 보인다(캔버스는 포커스가 카드를 감싼 노드 상자에
 * 가므로 그 상자의 `group` 으로 받는다).
 */
export function boardCardClassName({ isSelected, isDashed }: { isSelected: boolean; isDashed?: boolean }): string {
  return cn(
    "flex flex-col rounded-xl border border-border bg-background p-3 text-left break-keep hover:bg-muted motion-safe:transition-colors",
    isDashed && "border-dashed",
    isSelected && "border-solid border-ring inset-ring-1 inset-ring-ring",
  );
}

/** 화 카드 — 번호와 읽은 진행·수정안 표시, 제목, 요약 두 줄, 글자 수(다시 만드는 중이면 그 안내). */
export function EpisodeCardBody({ data }: { data: EpisodeNodeData }) {
  return (
    <>
      <span className="flex items-center justify-between gap-2 text-xs font-medium text-muted-foreground">
        <span className="tabular-nums">{data.ordinal}화</span>
        <span className="flex shrink-0 items-center gap-1.5">
          {data.hasPendingAiEdit && (
            <span className="flex items-center">
              <Sparkles aria-hidden className="size-3.5" />
              <span className="sr-only">AI 수정안이 있어요.</span>
            </span>
          )}
          <EpisodeReadMark readState={data.readState} />
        </span>
      </span>
      <span className={cn("mt-1 line-clamp-1 text-sm font-semibold", data.title === null ? "text-muted-foreground" : "text-foreground")}>
        {data.title ?? "제목 없음"}
      </span>
      <span className="mt-0.5 line-clamp-2 min-h-0 flex-1 text-xs text-muted-foreground">{data.summary}</span>
      {data.isRegenerating ? (
        <span className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          {/* 진행 표시라 동작 줄이기 설정에서도 돈다(멈추면 멈춘 화면으로 읽힌다). */}
          <Loader2 aria-hidden className="size-3.5 animate-spin" />
          다시 만드는 중
        </span>
      ) : (
        <span className="block mt-1 text-xs text-muted-foreground tabular-nums">{data.charCount.toLocaleString()}자</span>
      )}
    </>
  );
}

function EpisodeReadMark({ readState }: { readState: EpisodeNodeData["readState"] }) {
  switch (readState.kind) {
    case "finished":
      return (
        <span className="flex items-center">
          <CircleCheck aria-hidden className="size-3.5" />
          <span className="sr-only">다 읽었어요.</span>
        </span>
      );
    case "reading":
      return (
        <span className="tabular-nums">
          <span className="sr-only">읽는 중 </span>
          {readState.percent}%
        </span>
      );
    case "unread":
      return null;
  }
}

/** 인물 카드 — 이름, 메모 첫 줄, 나온 화 수. */
export function CharacterCardBody({ data }: { data: CharacterNodeData }) {
  const memoLine = data.memo.split("\n").find((line) => line.trim() !== "");
  return (
    <>
      <span className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-foreground">
        <UserRound aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        <span className="truncate">{data.name}</span>
      </span>
      <span className="mt-1 line-clamp-1 min-h-0 flex-1 text-xs text-muted-foreground">{memoLine ?? "메모 없음"}</span>
      <span className="block mt-1 text-xs text-muted-foreground tabular-nums">
        {data.appearanceCount > 0 ? `${data.appearanceCount}개 화에 나옴` : "지금 있는 화에는 안 나옴"}
      </span>
    </>
  );
}

/** 설정 노트 카드 — 앞부분 세 줄, 비었으면 쓰기로 부르는 문장. */
export function NotesCardBody({ data }: { data: NotesNodeData }) {
  const isEmpty = data.notes.trim() === "";
  return (
    <>
      <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <NotebookPen aria-hidden className="size-4 shrink-0 text-muted-foreground" />
        설정 노트
      </span>
      <span className="mt-1 line-clamp-3 min-h-0 text-xs whitespace-pre-line text-muted-foreground">
        {isEmpty ? "아직 없어요. 눌러서 써 보세요." : data.notes}
      </span>
    </>
  );
}
