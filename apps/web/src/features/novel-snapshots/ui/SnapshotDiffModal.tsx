import { Button } from "@ai-character-chat/ui/components/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import {
  useNovelCharactersQuery,
  useNovelQuery,
  useNovelRevisionQuery,
  useNovelSnapshotQuery,
} from "@/entities/novel";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { LazyDiffView } from "@/shared/ui/LazyDiffView";

import {
  toSnapshotChapterRows,
  toSnapshotCharacterRows,
  toSnapshotFieldRows,
  type SnapshotChapterRow,
} from "../model/snapshotCompare";

type SnapshotDiffModalProps = {
  novelId: string;
  snapshotId: string;
  snapshotName: string;
};

const BADGE = "inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium";

/** 버전 때와 지금의 비교. 위에서부터 소설 단위 칸(제목·소개·설정 노트), 화 목록, 인물 메모다. 차이는 늘 "버전 때 →
 * 지금"(그 뒤로 바뀐 것) 방향이다.
 *
 * 화 목록은 처음에 바뀐 화(그리고 지워진 화·그 뒤에 생긴 화)만 보이고, 바뀌지 않은 화는 토글로 펼친다 — 100화 중 두
 * 화를 고친 버전도 그 두 화가 바로 보이게. 화를 펼치면 그때 판과 지금 판의 본문을 받아 비교한다(판은 바뀌지 않아 한
 * 번 받은 것을 그대로 쓴다). 지워진 화는 내용이 남아 있지 않다 — 마지막 묶음을 지울 때 버전 안 그 화 항목도 지워진다.
 *
 * 닫는 것 말고 돌려줄 값이 없다. 편집 보드 라우트 안에만 마운트한다(비교 표시를 동적으로 불러오지만, 앱 루트 모달
 * 목록을 이 기능으로 늘리지 않는다). */
export const SnapshotDiffModal = createCallable<SnapshotDiffModalProps, void>(
  ({ call, novelId, snapshotId, snapshotName }) => {
    const novelQuery = useNovelQuery(novelId);
    const snapshotQuery = useNovelSnapshotQuery(novelId, snapshotId);
    const charactersQuery = useNovelCharactersQuery(novelId);

    return (
      <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle className="break-keep">‘{snapshotName}’과 지금 비교</DialogTitle>
            <DialogDescription className="break-keep">
              이 버전을 저장한 뒤 바뀐 곳이에요. 밑줄은 그 뒤에 더한 글, 취소선은 그 뒤에 지운 글이에요.
            </DialogDescription>
          </DialogHeader>
          <DialogBody scrollLabel="비교 내용" className="flex flex-col gap-6">
            <SnapshotDiffBody
              novelId={novelId}
              novelQuery={novelQuery}
              snapshotQuery={snapshotQuery}
              charactersQuery={charactersQuery}
            />
          </DialogBody>
        </DialogContent>
      </Dialog>
    );
  },
);

type SnapshotDiffBodyProps = {
  novelId: string;
  novelQuery: ReturnType<typeof useNovelQuery>;
  snapshotQuery: ReturnType<typeof useNovelSnapshotQuery>;
  charactersQuery: ReturnType<typeof useNovelCharactersQuery>;
};

/** 로딩·실패·내용이 배타적이라 순서대로 일찍 돌려준다. 모달 표면 위라 자리 표시는 `secondary` 다. */
function SnapshotDiffBody({ novelId, novelQuery, snapshotQuery, charactersQuery }: SnapshotDiffBodyProps) {
  const [isShowingUnchanged, setIsShowingUnchanged] = useState(false);
  const novelHeadingId = useId();
  const chaptersHeadingId = useId();
  const charactersHeadingId = useId();

  if (novelQuery.isPending || snapshotQuery.isPending) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((index) => (
          <div key={index} className="h-11 animate-pulse rounded-lg bg-secondary" />
        ))}
      </div>
    );
  }
  if (novelQuery.data === undefined || snapshotQuery.data === undefined) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm break-keep text-destructive-text">비교할 내용을 불러오지 못했어요. 잠시 후 다시 시도해주세요.</p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            void novelQuery.refetch();
            void snapshotQuery.refetch();
          }}
        >
          다시 시도
        </Button>
      </div>
    );
  }

  const novel = novelQuery.data;
  const snapshot = snapshotQuery.data;
  const fieldRows = toSnapshotFieldRows(snapshot, novel);
  const chapterRows = toSnapshotChapterRows(snapshot, novel.chapters);
  const shownChapterRows = isShowingUnchanged
    ? chapterRows
    : chapterRows.filter((row) => row.kind !== "kept" || row.isChanged);
  const unchangedCount = chapterRows.length - chapterRows.filter((row) => row.kind !== "kept" || row.isChanged).length;
  const characterRows =
    charactersQuery.data === undefined ? undefined : toSnapshotCharacterRows(snapshot, charactersQuery.data).filter((row) => row.isChanged);

  return (
    <>
      <section aria-labelledby={novelHeadingId} className="flex flex-col gap-2">
        <h3 id={novelHeadingId} className="text-sm font-semibold">
          소설
        </h3>
        <ul className="flex flex-col">
          {fieldRows.map((row) =>
            row.isChanged ? (
              <DisclosureRow key={row.label} summary={<span className="font-medium">{row.label}</span>} badge="바뀜">
                <LazyDiffView before={row.before} after={row.after} />
              </DisclosureRow>
            ) : (
              <li key={row.label} className="flex min-h-11 items-center gap-2 border-b border-border text-sm last:border-b-0">
                <span className="font-medium">{row.label}</span>
                <span className="text-muted-foreground">그대로</span>
              </li>
            ),
          )}
        </ul>
      </section>

      <section aria-labelledby={chaptersHeadingId} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 id={chaptersHeadingId} className="text-sm font-semibold">
            화
          </h3>
          {unchangedCount > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-pressed={isShowingUnchanged}
              className="hover:bg-secondary aria-pressed:bg-secondary"
              onClick={() => setIsShowingUnchanged((shown) => !shown)}
            >
              바뀌지 않은 화 {unchangedCount}개도 보기
            </Button>
          )}
        </div>
        {shownChapterRows.length === 0 ? (
          <p className="text-sm break-keep text-muted-foreground">이 버전 뒤로 바뀐 화가 없어요.</p>
        ) : (
          <ul className="flex flex-col">
            {shownChapterRows.map((row) => (
              <SnapshotChapterRowView key={row.chapterId} novelId={novelId} row={row} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby={charactersHeadingId} className="flex flex-col gap-2">
        <h3 id={charactersHeadingId} className="text-sm font-semibold">
          인물 메모
        </h3>
        {characterRows === undefined && (
          <p className="text-sm break-keep text-muted-foreground">
            {charactersQuery.isPending ? "인물을 불러오는 중이에요." : "인물을 불러오지 못했어요."}
          </p>
        )}
        {characterRows?.length === 0 && (
          <p className="text-sm break-keep text-muted-foreground">이 버전 뒤로 바뀐 인물 메모가 없어요.</p>
        )}
        {characterRows !== undefined && characterRows.length > 0 && (
          <ul className="flex flex-col">
            {characterRows.map((row) => (
              <DisclosureRow
                key={row.snapshotCharacterId}
                summary={
                  <span className="min-w-0 break-keep">
                    <span className="font-medium">{row.currentName ?? row.snapshotName}</span>
                    {row.isMerged && (
                      <span className="text-muted-foreground"> · ‘{row.snapshotName}’ 카드가 합쳐졌어요</span>
                    )}
                    {row.currentName === undefined && <span className="text-muted-foreground"> · 지금은 카드가 없어요</span>}
                  </span>
                }
                badge="바뀜"
              >
                <LazyDiffView before={row.beforeMemo} after={row.afterMemo} />
              </DisclosureRow>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function SnapshotChapterRowView({ novelId, row }: { novelId: string; row: SnapshotChapterRow }) {
  if (row.kind === "deleted") {
    return (
      <li className="flex min-h-11 items-center gap-2 border-b border-border text-sm last:border-b-0">
        <span className="min-w-0 flex-1 break-keep text-muted-foreground">이 버전에 있던 화</span>
        <span className={cn(BADGE, "border-transparent bg-destructive/10 text-destructive-text")}>지워진 화</span>
      </li>
    );
  }
  if (row.kind === "added") {
    return (
      <li className="flex min-h-11 items-center gap-2 border-b border-border text-sm last:border-b-0">
        <span className="min-w-0 flex-1 break-keep">
          <span className="font-medium tabular-nums">{row.ordinal}화</span>
          {row.title !== null && <span className="text-muted-foreground"> {row.title}</span>}
        </span>
        <span className={BADGE}>이 버전 뒤에 생긴 화</span>
      </li>
    );
  }
  const summary = (
    <span className="min-w-0 break-keep">
      <span className="font-medium tabular-nums">{row.ordinal}화</span>
      {row.currentTitle !== null && <span className="text-muted-foreground"> {row.currentTitle}</span>}
    </span>
  );
  if (!row.isChanged) {
    return (
      <li className="flex min-h-11 items-center gap-2 border-b border-border text-sm last:border-b-0">
        <span className="min-w-0 flex-1">{summary}</span>
        <span className="shrink-0 text-xs text-muted-foreground">그대로</span>
      </li>
    );
  }
  return (
    <DisclosureRow summary={summary} badge="바뀜">
      <ChapterDiff novelId={novelId} row={row} />
    </DisclosureRow>
  );
}

function ChapterDiff({ novelId, row }: { novelId: string; row: Extract<SnapshotChapterRow, { kind: "kept" }> }) {
  const isBodyChanged = row.snapshotRevisionId !== row.currentRevisionId;
  const beforeQuery = useNovelRevisionQuery(novelId, row.chapterId, isBodyChanged ? (row.snapshotRevisionId ?? undefined) : undefined);
  const afterQuery = useNovelRevisionQuery(novelId, row.chapterId, isBodyChanged ? row.currentRevisionId : undefined);

  return (
    <div className="flex flex-col gap-4">
      {row.snapshotTitle !== row.currentTitle && (
        <p className="text-sm break-keep">
          <span className="text-muted-foreground">제목 </span>
          {row.snapshotTitle ?? "(없음)"} → {row.currentTitle ?? "(없음)"}
        </p>
      )}
      {row.snapshotAuthorNote !== row.currentAuthorNote && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-muted-foreground">작가의 말</p>
          <LazyDiffView before={row.snapshotAuthorNote} after={row.currentAuthorNote} />
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <p className="text-xs text-muted-foreground">본문</p>
        {!isBodyChanged && <p className="text-sm text-muted-foreground">본문은 그대로예요.</p>}
        {isBodyChanged && row.snapshotRevisionId === null && (
          <p className="text-sm break-keep text-muted-foreground">이 버전 때 글이 남아 있지 않아 비교할 수 없어요.</p>
        )}
        {isBodyChanged && row.snapshotRevisionId !== null && (beforeQuery.isPending || afterQuery.isPending) && (
          <div className="h-24 animate-pulse rounded-lg bg-secondary" />
        )}
        {isBodyChanged && row.snapshotRevisionId !== null && (beforeQuery.isError || afterQuery.isError) && (
          <p className="text-sm break-keep text-destructive-text">본문을 불러오지 못했어요.</p>
        )}
        {beforeQuery.data !== undefined && afterQuery.data !== undefined && (
          <LazyDiffView before={beforeQuery.data.body} after={afterQuery.data.body} />
        )}
      </div>
    </div>
  );
}

type DisclosureRowProps = { summary: ReactNode; badge: string; children: ReactNode };

/** 펼치는 행 하나. 머리 줄 전체가 버튼이다(`aria-expanded`). hover 면은 `secondary` 반투명 — 모달 표면 위라 `muted` 는
 * 사라진다. 펼친 내용은 펼칠 때만 그려 본문 비교를 그때 받는다. */
function DisclosureRow({ summary, badge, children }: DisclosureRowProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const panelId = useId();

  return (
    <li className="flex flex-col border-b border-border last:border-b-0">
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={panelId}
        className="-mx-2 flex min-h-11 items-center gap-2 rounded-md px-2 py-2 text-left text-sm outline-none motion-safe:transition-colors hover:bg-secondary/50 focus-visible:ring-3 focus-visible:ring-ring/50"
        onClick={() => setIsExpanded((open) => !open)}
      >
        <span className="flex min-w-0 flex-1 items-center gap-2">{summary}</span>
        <span className={BADGE}>{badge}</span>
        <ChevronDown
          aria-hidden
          className={cn("size-4 shrink-0 text-muted-foreground motion-safe:transition-transform", isExpanded && "rotate-180")}
        />
      </button>
      {isExpanded && (
        <div id={panelId} className="pt-1 pb-4">
          {children}
        </div>
      )}
    </li>
  );
}
