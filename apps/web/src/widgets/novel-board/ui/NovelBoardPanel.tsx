import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ArrowLeft } from "lucide-react";
import type { KeyboardEvent, ReactNode, RefObject } from "react";

import { useNovelCharactersQuery, type NovelDetailResponse } from "@/entities/novel";
import type { NovelChapterJobFlow } from "@/features/create-novel-chapter";
import type { NovelAiEditFlow } from "@/features/edit-novel-chapter";
import { CharacterCardEditor } from "@/features/edit-novel-character";
import { NovelNotesEditor } from "@/features/edit-novel-notes";
import { NovelSnapshotsPanel } from "@/features/novel-snapshots";

import type { BoardSelection } from "../model/boardSelection";

import { BoardEpisodePanel } from "./BoardEpisodePanel";
import { BoardOverviewPanel } from "./BoardOverviewPanel";
import { NovelPlanDocument } from "./NovelPlanDocument";

type NovelBoardPanelProps = {
  novel: NovelDetailResponse;
  /** 고른 것(지금 있는 대상으로 이미 걸렀다). 없으면 소설 개요다. */
  selection: BoardSelection | undefined;
  chapterFlow: NovelChapterJobFlow;
  aiEdit: NovelAiEditFlow;
  /** 패널 제목. 고를 때 호출부가 여기로 포커스를 보낸다. */
  headingRef: RefObject<HTMLHeadingElement | null>;
  onSelect: (selection: BoardSelection | undefined) => void;
  /** 고르기를 풀고 돌아가기. 주면 맨 위에 돌아가기 버튼을 둔다 — 좁은 화면의 목록으로, 넓은 화면의 구성 모드에서는 캔버스로. */
  onBackToList?: () => void;
  /** 돌아가기 버튼 이름. 없으면 "목록"이다. */
  backLabel?: string;
  /** 개요의 구성 화면 입구. 구성 흐름 스위치가 켜졌을 때만 호출부가 준다. */
  planEntry?: ReactNode;
  onChapterDeleted: (firstDeletedOrdinal: number, deletedChapterIds: string[]) => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/**
 * 편집 보드의 패널 — 고른 것에 따라 화(본문 고치기)·인물 카드·설정 노트·버전·구성 모드, 고른 것이 없으면 소설 개요. 넓은
 * 화면에서는 캔버스 오른쪽 열, 좁은 화면에서는 목록 자리를 대신하는 화면이다(시트가 아니다 — 시트 표면에서는 문단
 * 버튼의 hover 가 사라지고, 긴 본문 편집이 시트 안 스크롤이 되며, 수정·이력 모달이 시트 위로 겹친다).
 *
 * 이 컴포넌트가 스크롤 영역이다. 호출부가 고른 것으로 `key` 를 주어 고를 때마다 새로 마운트한다 — 고치던 글과 고치기
 * 모드는 그 대상에만 속하고, 새로 고른 패널은 맨 위에서 시작한다. 서버 데이터가 다시 와도 같은 대상이면 다시 마운트하지
 * 않아 쓰던 글이 남는다.
 *
 * `Esc` 는 고르기를 푼다(입력칸 안이나, 메뉴·선택 상자가 먼저 받은 `Esc` 는 빼고).
 */
export function NovelBoardPanel({
  novel,
  selection,
  chapterFlow,
  aiEdit,
  headingRef,
  onSelect,
  onBackToList,
  backLabel = "목록",
  planEntry,
  onChapterDeleted,
  onDraftDirtyChange,
}: NovelBoardPanelProps) {
  const charactersQuery = useNovelCharactersQuery(novel.id);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape" || event.defaultPrevented || selection === undefined) return;
    if (isTextEntry(event.target)) return;
    onSelect(undefined);
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto" onKeyDown={handleKeyDown}>
      {/* 구성 모드는 문서라 넓은 화면에서도 읽기 좋은 폭(최대 672px)의 가운데 한 열이다. */}
      <div
        className={cn("flex flex-col gap-6 px-4 py-6 sm:px-6", selection?.kind === "plan" && "mx-auto w-full max-w-2xl")}
      >
        {onBackToList !== undefined && (
          <Button type="button" variant="ghost" size="sm" className="-ml-2 self-start" onClick={onBackToList}>
            <ArrowLeft aria-hidden />
            {backLabel}
          </Button>
        )}
        <PanelContent
          novel={novel}
          selection={selection}
          charactersQuery={charactersQuery}
          chapterFlow={chapterFlow}
          aiEdit={aiEdit}
          headingRef={headingRef}
          onSelect={onSelect}
          planEntry={planEntry}
          onChapterDeleted={onChapterDeleted}
          onDraftDirtyChange={onDraftDirtyChange}
        />
      </div>
    </div>
  );
}

type PanelContentProps = Omit<NovelBoardPanelProps, "onBackToList" | "backLabel"> & {
  charactersQuery: ReturnType<typeof useNovelCharactersQuery>;
};

function PanelContent({
  novel,
  selection,
  charactersQuery,
  chapterFlow,
  aiEdit,
  headingRef,
  onSelect,
  planEntry,
  onChapterDeleted,
  onDraftDirtyChange,
}: PanelContentProps) {
  if (selection === undefined) {
    return (
      <BoardOverviewPanel
        novel={novel}
        characterCount={charactersQuery.data?.length}
        headingRef={headingRef}
        planEntry={planEntry}
      />
    );
  }

  switch (selection.kind) {
    case "episode": {
      const chapter = novel.chapters.find((item) => item.id === selection.id);
      // 고른 것은 호출부가 지금 있는 화로 걸러 준다 — 여기 없다면 상세가 그사이 바뀐 한 렌더뿐이다.
      if (chapter === undefined) return null;
      return (
        <BoardEpisodePanel
          novel={novel}
          chapter={chapter}
          chapterFlow={chapterFlow}
          aiEdit={aiEdit}
          headingRef={headingRef}
          onChapterDeleted={onChapterDeleted}
          onDraftDirtyChange={onDraftDirtyChange}
        />
      );
    }
    case "character":
      return (
        <CharacterPanel
          novel={novel}
          characterId={selection.id}
          query={charactersQuery}
          headingRef={headingRef}
          onSelect={onSelect}
          onDraftDirtyChange={onDraftDirtyChange}
        />
      );
    case "notes":
      return <NovelNotesEditor novel={novel} headingRef={headingRef} onDraftDirtyChange={onDraftDirtyChange} />;
    case "versions":
      return (
        <NovelSnapshotsPanel
          novel={novel}
          headingRef={headingRef}
          // 되돌리면 화 본문이 바뀌어 화 머리에 남은 지난 고치기 결과는 옛 글의 이야기가 된다.
          onRestored={() => aiEdit.report({ type: "started" })}
        />
      );
    case "plan":
      return <NovelPlanDocument novel={novel} headingRef={headingRef} onDraftDirtyChange={onDraftDirtyChange} />;
  }
}

type CharacterPanelProps = {
  novel: NovelDetailResponse;
  characterId: string;
  query: ReturnType<typeof useNovelCharactersQuery>;
  headingRef: RefObject<HTMLHeadingElement | null>;
  onSelect: (selection: BoardSelection | undefined) => void;
  onDraftDirtyChange: (isDirty: boolean) => void;
};

/** 인물 카드. 인물 목록을 받는 중이면 막대, 못 받았으면 다시 시도. 고른 인물은 호출부가 목록으로 이미 걸렀다. */
function CharacterPanel({ novel, characterId, query, headingRef, onSelect, onDraftDirtyChange }: CharacterPanelProps) {
  if (query.data === undefined) {
    if (query.isError) {
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm break-keep text-muted-foreground">인물을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-disabled={query.isFetching}
            className="aria-disabled:opacity-65"
            onClick={() => {
              if (query.isFetching) return;
              void query.refetch();
            }}
          >
            다시 시도
          </Button>
        </div>
      );
    }
    return (
      <div aria-hidden className="flex flex-col gap-3">
        <div className="h-7 w-1/3 animate-pulse rounded-lg bg-muted" />
        <div className="h-24 animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const character = query.data.find((item) => item.id === characterId);
  if (character === undefined) return null;
  return (
    <CharacterCardEditor
      key={character.id}
      novel={novel}
      character={character}
      characters={query.data}
      headingRef={headingRef}
      onSelectEpisode={(chapterId) => onSelect({ kind: "episode", id: chapterId })}
      onMerged={(intoCharacterId) => onSelect({ kind: "character", id: intoCharacterId })}
      onDraftDirtyChange={onDraftDirtyChange}
    />
  );
}

/** 글을 쓰는 자리인가 — 거기서 누른 `Esc` 는 입력을 접는 데 쓰이고 고르기를 풀지 않는다. */
function isTextEntry(target: EventTarget): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
}
