import { Button } from "@ai-character-chat/ui/components/button";
import { cn } from "@ai-character-chat/ui/lib/utils";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, RotateCcw } from "lucide-react";
import { useId, useState } from "react";

import {
  CHAPTER_REGENERATING_MESSAGE,
  isChapterRegenerating,
  novelKeys,
  toNovelActionError,
  useNovelQuery,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { formatRelativeTime } from "@/shared/lib/time/formatRelativeTime";

import { useNovelRevisionQuery } from "../api/useNovelRevisionQuery";
import { useNovelRevisionsQuery, type NovelRevisionSummary } from "../api/useNovelRevisionsQuery";
import { useRestoreRevisionMutation } from "../api/useRestoreRevisionMutation";
import { toRevisionSourceLabel } from "../model/revisionLabel";

type NovelRevisionHistoryModalProps = {
  novelId: string;
  chapterId: string;
  chapterOrdinal: number;
  /** 이 장에 적용하지 않은 AI 수정안이 있는가. 되돌리면 서버가 그 수정안을 버린다. */
  hasPendingAiEdits: boolean;
};

/** 장 하나의 판 이력. 판을 펼치면 그 판의 글이 보이고, 옛 판은 되돌릴 수 있다. 되돌리기는 옛 판을 **새 판으로**
 * 쌓는다 — 지금 글을 지우지 않는다. 돌려주는 값은 되돌린 옛 판의 번호, 되돌리지 않고 닫았으면 `null` 이다(되돌렸으면
 * 호출부가 그 번호로 결과를 알리고 장 머리로 포커스를 옮긴다 — 모달을 연 버튼은 남아 있지만, 바뀐 본문의 시작으로
 * 보내는 쪽이 결과를 알려 준다).
 *
 * 되돌리기의 기준 판은 목록 맨 앞(지금 판)이다. 그사이 다른 곳에서 새 판이 생겼으면 서버가 409 로 막고, 목록을
 * 다시 받아 기준이 새 판으로 바뀐다 — 이용자는 새로 생긴 판을 목록에서 보고 다시 고를 수 있다. 실패 문장은
 * 누른 순간 기록한 상태라 목록을 다시 받아도 남는다.
 *
 * 이 장을 다시 만드는 작업이 도는 동안은 되돌리기를 막고 사유를 단다 — 다시 만든 글이 그때의 최신 판 위에 쌓여
 * 되돌린 판을 밀어낸다. 모달이 열린 사이에 작업이 끝나거나 시작될 수 있어 연 순간의 값이 아니라 소설 상세를 따라
 * 읽는다. 상세는 받은 즉시 낡은 것으로 치는 쿼리라 모달을 열 때 한 번 다시 받는다 — 연 순간의 진행 중 작업도 그만큼
 * 최신이 된다. */
export const NovelRevisionHistoryModal = createCallable<NovelRevisionHistoryModalProps, number | null>(
  ({ call, novelId, chapterId, chapterOrdinal, hasPendingAiEdits }) => {
    const queryClient = useQueryClient();
    const revisionsQuery = useNovelRevisionsQuery(novelId, chapterId);
    const restoreMutation = useRestoreRevisionMutation();
    const novelQuery = useNovelQuery(novelId);
    const isRegenerating = isChapterRegenerating(novelQuery.data?.activeJob ?? null, chapterId);
    const [expandedId, setExpandedId] = useState<string | undefined>(undefined);
    const [restoreError, setRestoreError] = useState<string | undefined>(undefined);
    const revisions = revisionsQuery.data ?? [];
    const current = revisions[0];

    async function restore(revision: NovelRevisionSummary) {
      if (restoreMutation.isPending || isRegenerating || current === undefined) return;
      setRestoreError(undefined);
      try {
        await restoreMutation.mutateAsync({
          novelId,
          chapterId,
          revisionId: revision.id,
          baseRevisionId: current.id,
        });
        call.end(revision.revisionNo);
      } catch (error) {
        const result = toNovelActionError(error, "restore");
        // 재동의가 필요하면 전역 재동의 모달이 뜬다 — 그 위에 이 모달을 남겨 두지 않는다.
        if (result === null) {
          call.end(null);
          return;
        }
        setRestoreError(result.message);
        // 기준이 낡았으면(409) 목록부터 다시 받는다 — 맨 앞이 새 기준이 된다.
        void queryClient.invalidateQueries({ queryKey: novelKeys.revisions(novelId, chapterId) });
        if (result.shouldRefetchNovel) void queryClient.invalidateQueries({ queryKey: novelKeys.detail(novelId) });
      }
    }

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{chapterOrdinal}장 판 이력</DialogTitle>
            <DialogDescription className="break-keep">
              판을 펼쳐 그때의 글을 볼 수 있어요. 옛 판으로 되돌리면 그 글이 새 판으로 쌓이고, 지금 글도 이력에 남아요.
            </DialogDescription>
          </DialogHeader>

          <DialogBody scrollLabel="판 목록" className="flex flex-col gap-3">
            {restoreError !== undefined && (
              <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm break-keep text-destructive-text">
                {restoreError}
              </p>
            )}
            <RevisionListBody
              query={revisionsQuery}
              novelId={novelId}
              chapterId={chapterId}
              expandedId={expandedId}
              isRestoring={restoreMutation.isPending}
              isRegenerating={isRegenerating}
              hasPendingAiEdits={hasPendingAiEdits}
              onToggle={(id) => setExpandedId((open) => (open === id ? undefined : id))}
              onRestore={(revision) => void restore(revision)}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>
    );
  },
);

type RevisionListBodyProps = {
  query: ReturnType<typeof useNovelRevisionsQuery>;
  novelId: string;
  chapterId: string;
  expandedId: string | undefined;
  isRestoring: boolean;
  isRegenerating: boolean;
  hasPendingAiEdits: boolean;
  onToggle: (id: string) => void;
  onRestore: (revision: NovelRevisionSummary) => void;
};

/** 로딩·실패·목록이 배타적이라 순서대로 일찍 돌려준다. 모달 표면(`popover`) 위라 자리 표시는 `bg-secondary` 다 —
 * `bg-muted` 는 그 표면과 값이 같아 사라진다. */
function RevisionListBody({
  query,
  novelId,
  chapterId,
  expandedId,
  isRestoring,
  isRegenerating,
  hasPendingAiEdits,
  onToggle,
  onRestore,
}: RevisionListBodyProps) {
  if (query.isPending) {
    return (
      <ul className="flex flex-col gap-2">
        {[0, 1, 2].map((index) => (
          <li key={index} className="h-11 animate-pulse rounded-lg bg-secondary" />
        ))}
      </ul>
    );
  }

  if (query.data === undefined) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm break-keep text-destructive-text">판 이력을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
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

  const now = new Date();
  return (
    <ul className="flex flex-col">
      {query.data.map((revision, index) => (
        <RevisionRow
          key={revision.id}
          revision={revision}
          label={toRevisionSourceLabel(revision, query.data)}
          time={formatRelativeTime(revision.createdAt, now)}
          isCurrent={index === 0}
          isExpanded={expandedId === revision.id}
          isRestoring={isRestoring}
          isRegenerating={isRegenerating}
          hasPendingAiEdits={hasPendingAiEdits}
          novelId={novelId}
          chapterId={chapterId}
          onToggle={() => onToggle(revision.id)}
          onRestore={() => onRestore(revision)}
        />
      ))}
    </ul>
  );
}

type RevisionRowProps = {
  revision: NovelRevisionSummary;
  label: string;
  time: string;
  isCurrent: boolean;
  isExpanded: boolean;
  isRestoring: boolean;
  /** 이 장을 다시 만드는 중인가. 그동안은 되돌리기를 막는다. */
  isRegenerating: boolean;
  hasPendingAiEdits: boolean;
  novelId: string;
  chapterId: string;
  onToggle: () => void;
  onRestore: () => void;
};

/** 판 하나. 머리 줄 전체가 펼치기 버튼이고(`aria-expanded`), 되돌리기 버튼은 펼친 본문 아래에 있다 — 글을 보지
 * 않고 되돌리는 일이 없게. 지금 판에는 되돌리기가 없다. hover 면은 `secondary` 반투명이다 — 불투명 `secondary` 위의
 * 흐린 글자는 라이트에서 4.5:1 아래로 떨어진다(대화상자 푸터 띠가 반투명인 것과 같은 이유). */
function RevisionRow({
  revision,
  label,
  time,
  isCurrent,
  isExpanded,
  isRestoring,
  isRegenerating,
  hasPendingAiEdits,
  novelId,
  chapterId,
  onToggle,
  onRestore,
}: RevisionRowProps) {
  const panelId = useId();
  const pendingNoteId = useId();
  const regeneratingNoteId = useId();
  const isRestoreBlocked = isRestoring || isRegenerating;
  const restoreDescribedBy = [isRegenerating && regeneratingNoteId, hasPendingAiEdits && pendingNoteId]
    .filter((part) => part !== false)
    .join(" ");

  return (
    <li className="flex flex-col border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={panelId}
        className="-mx-2 flex min-h-11 items-center gap-2 rounded-md px-2 py-2 text-left text-sm outline-none motion-safe:transition-colors hover:bg-secondary/50 focus-visible:ring-3 focus-visible:ring-ring/50"
        onClick={onToggle}
      >
        <span className="font-medium text-foreground tabular-nums">{revision.revisionNo}판</span>
        <span className="min-w-0 flex-1 break-keep text-muted-foreground">
          {label} · {time}
        </span>
        {isCurrent && <span className="shrink-0 text-xs font-medium text-foreground">지금 글</span>}
        <ChevronDown
          aria-hidden
          className={cn("size-4 shrink-0 text-muted-foreground motion-safe:transition-transform", isExpanded && "rotate-180")}
        />
      </button>
      {isExpanded && (
        <div id={panelId} className="flex flex-col gap-3 pt-1 pb-3">
          <RevisionBody novelId={novelId} chapterId={chapterId} revisionId={revision.id} />
          {!isCurrent && isRegenerating && (
            <p id={regeneratingNoteId} className="text-sm break-keep text-muted-foreground">
              {CHAPTER_REGENERATING_MESSAGE}
            </p>
          )}
          {!isCurrent && hasPendingAiEdits && (
            <p id={pendingNoteId} className="text-sm break-keep text-muted-foreground">
              되돌리면 이 장에서 적용하지 않은 AI 수정안은 사라지고, 쓴 클로버는 돌아오지 않아요.
            </p>
          )}
          {!isCurrent && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-disabled={isRestoreBlocked}
              aria-describedby={restoreDescribedBy || undefined}
              className="self-start aria-disabled:opacity-65"
              onClick={() => {
                if (isRestoreBlocked) return;
                onRestore();
              }}
            >
              <RotateCcw aria-hidden />
              {isRestoring ? "되돌리는 중…" : `${revision.revisionNo}판으로 되돌리기`}
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

function RevisionBody({ novelId, chapterId, revisionId }: { novelId: string; chapterId: string; revisionId: string }) {
  const query = useNovelRevisionQuery(novelId, chapterId, revisionId);

  if (query.isPending) {
    return <div className="h-24 animate-pulse rounded-lg bg-secondary" />;
  }
  if (query.data === undefined) {
    return <p className="text-sm break-keep text-destructive-text">이 판의 글을 불러오지 못했어요.</p>;
  }
  return (
    <div className="flex flex-col gap-3 text-sm leading-relaxed break-keep whitespace-pre-line text-foreground">
      {query.data.paragraphs.map((paragraph, index) => (
        // 판은 바뀌지 않아 순서가 곧 정체성이다.
        <p key={index}>{paragraph}</p>
      ))}
    </div>
  );
}
