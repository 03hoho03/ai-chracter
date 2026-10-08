import { Button } from "@ai-character-chat/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ai-character-chat/ui/components/dropdown-menu";
import { GitCompare, MoreHorizontal, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useId, useRef, useState, type RefObject } from "react";

import {
  useNovelSnapshotsQuery,
  type NovelDetailResponse,
  type NovelSnapshotSummary,
} from "@/entities/novel";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

import { toSkippedChaptersNotice } from "../model/snapshotCompare";
import { toDefaultSnapshotName } from "../model/snapshotName";
import { formatSnapshotTime } from "../model/snapshotTime";
import { DeleteSnapshotModal } from "./DeleteSnapshotModal";
import { RestoreSnapshotModal } from "./RestoreSnapshotModal";
import { SaveSnapshotModal } from "./SaveSnapshotModal";
import { SnapshotDiffModal } from "./SnapshotDiffModal";

type NovelSnapshotsPanelProps = {
  novel: NovelDetailResponse;
  /** 패널 제목(`h2`, `tabIndex=-1`). 호출부가 패널을 열 때 포커스를 보낼 자리다. 주지 않으면 패널이 자기 것을 쓴다. */
  headingRef?: RefObject<HTMLHeadingElement | null>;
  /** 되돌리기가 끝난 뒤. 화 본문이 그때 판으로 바뀌어, 호출부가 들고 있는 낡은 안내(지난 고치기 결과)를 지운다. */
  onRestored?: () => void;
};

const RESTORE_BLOCKED_REASON = "만들고 있는 화가 끝나면 되돌릴 수 있어요.";

/**
 * 편집 보드의 버전 패널 — 지금 상태 저장, 저장한 버전 목록, 버전마다 지금과 비교·되돌리기·지우기.
 *
 * - 저장 버튼은 `outline` 이다. 이 화면의 솔리드 채움은 상단 바의 "다음 화 만들기" 하나다.
 * - 화를 만드는 동안은 되돌리기를 `aria-disabled` + 바로 아래 이유로 막는다(서버도 거부한다 — 생성 결과가 같은 화를
 *   고친다). 지우기는 화 작업과 부딪히지 않아 막지 않는다.
 * - 되돌린 결과는 늘 마운트된 `role="status"` 줄에 남긴다(조건부로 붙이면 붙는 순간을 화면 낭독기가 놓친다). 건너뛴
 *   화가 있으면 함께 말한다. 다음 저장·되돌리기·지우기에서 지운다.
 * - 지우면 그 행과 메뉴가 사라져 돌아갈 자리가 없으므로, 모달이 닫힌 뒤 포커스를 패널 제목으로 옮긴다.
 *
 * 이 패널이 여는 모달 넷(`SaveSnapshotModal`·`RestoreSnapshotModal`·`DeleteSnapshotModal`·`SnapshotDiffModal`)은 이
 * 패널을 그리는 라우트가 마운트하고, 그 라우트를 떠날 때 닫는다.
 */
export function NovelSnapshotsPanel({ novel, headingRef, onRestored }: NovelSnapshotsPanelProps) {
  const localHeadingRef = useRef<HTMLHeadingElement>(null);
  const titleRef = headingRef ?? localHeadingRef;
  const headingId = useId();
  const query = useNovelSnapshotsQuery(novel.id);
  const [result, setResult] = useState<string | undefined>(undefined);
  const isJobRunning = novel.activeJob !== null;

  async function save() {
    setResult(undefined);
    const saved = await SaveSnapshotModal.call({
      novelId: novel.id,
      maxLength: novel.limits.snapshotNameMaxLength,
      defaultName: toDefaultSnapshotName(novel.chapters.map((chapter) => chapter.ordinal)),
    });
    if (saved !== null) setResult(`‘${saved.name}’${koreanParticle(saved.name, "으로/로")} 저장했어요.`);
  }

  async function restore(snapshot: NovelSnapshotSummary) {
    if (isJobRunning) return;
    setResult(undefined);
    const restored = await RestoreSnapshotModal.call({
      novelId: novel.id,
      snapshotId: snapshot.id,
      snapshotName: snapshot.name,
    });
    if (restored === null) return;
    onRestored?.();
    const skipped = toSkippedChaptersNotice(restored.skippedChapters, restored.novel.chapters);
    setResult([`‘${snapshot.name}’ 때로 되돌렸어요.`, skipped].filter((part) => part !== undefined).join(" "));
  }

  async function remove(snapshot: NovelSnapshotSummary) {
    setResult(undefined);
    const isDeleted = await DeleteSnapshotModal.call({
      novelId: novel.id,
      snapshotId: snapshot.id,
      snapshotName: snapshot.name,
      // 지운 행과 그 메뉴가 사라지므로 패널 제목으로 보낸다.
      onRestoreFocusAfterDelete: () => titleRef.current?.focus(),
    });
    if (!isDeleted) return;
    setResult(`‘${snapshot.name}’${koreanParticle(snapshot.name, "을/를")} 지웠어요.`);
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <h2 ref={titleRef} id={headingId} tabIndex={-1} className="text-lg font-semibold outline-none">
          버전
        </h2>
        <p className="text-sm break-keep text-muted-foreground">
          지금 상태에 이름을 붙여 남겨 두고, 언제든 그때로 되돌릴 수 있어요.
        </p>
        {/* 비어 있어도 마운트해 둔다 — 붙는 순간의 결과 문장을 화면 낭독기가 놓치지 않게. */}
        <p role="status" className="text-sm break-keep text-foreground">
          {result}
        </p>
      </div>

      <Button type="button" variant="outline" className="self-start" onClick={() => void save()}>
        <Plus aria-hidden />
        지금 상태 저장
      </Button>

      <SnapshotList
        query={query}
        isRestoreBlocked={isJobRunning}
        onCompare={(snapshot) =>
          void SnapshotDiffModal.call({ novelId: novel.id, snapshotId: snapshot.id, snapshotName: snapshot.name })
        }
        onRestore={(snapshot) => void restore(snapshot)}
        onDelete={(snapshot) => void remove(snapshot)}
      />

      {query.data !== undefined && (
        <p className="text-xs break-keep text-muted-foreground tabular-nums">
          {query.data.items.length}/{query.data.limit}개 · 가득 차면 자동 저장부터 지워지고, 이름 붙인 것만 남으면 새로
          저장할 수 없어요.
        </p>
      )}
    </section>
  );
}

type SnapshotListProps = {
  query: ReturnType<typeof useNovelSnapshotsQuery>;
  isRestoreBlocked: boolean;
  onCompare: (snapshot: NovelSnapshotSummary) => void;
  onRestore: (snapshot: NovelSnapshotSummary) => void;
  onDelete: (snapshot: NovelSnapshotSummary) => void;
};

/** 로딩·실패·빈 목록·목록이 배타적이라 순서대로 일찍 돌려준다. 패널은 페이지 배경 위라 자리 표시는 `muted` 다. */
function SnapshotList({ query, isRestoreBlocked, onCompare, onRestore, onDelete }: SnapshotListProps) {
  if (query.isPending) {
    return (
      <ul aria-hidden className="flex flex-col gap-2">
        {[0, 1, 2].map((index) => (
          <li key={index} className="h-11 animate-pulse rounded-lg bg-muted" />
        ))}
      </ul>
    );
  }
  if (query.data === undefined) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-sm break-keep text-destructive-text">버전 목록을 불러오지 못했어요.</p>
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
  if (query.data.items.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border p-4 text-sm break-keep text-muted-foreground">
        아직 저장한 버전이 없어요. 크게 고치기 전에 지금 상태를 남겨 두면 언제든 돌아올 수 있어요.
      </p>
    );
  }
  return (
    <ul className="flex flex-col border-t border-border">
      {query.data.items.map((snapshot) => (
        <SnapshotRow
          key={snapshot.id}
          snapshot={snapshot}
          isRestoreBlocked={isRestoreBlocked}
          onCompare={() => onCompare(snapshot)}
          onRestore={() => onRestore(snapshot)}
          onDelete={() => onDelete(snapshot)}
        />
      ))}
    </ul>
  );
}

type SnapshotRowProps = {
  snapshot: NovelSnapshotSummary;
  isRestoreBlocked: boolean;
  onCompare: () => void;
  onRestore: () => void;
  onDelete: () => void;
};

/** 버전 한 줄 — 이름, 자동 저장 표시, 저장 시각, ⋯ 메뉴. 되돌리기를 못 하면 항목 바로 아래 이유를 두고
 * `aria-describedby` 로 잇는다(구분선은 이유 아래, 지우기 앞에만 — 이유는 다음 무리의 머리가 아니다). */
function SnapshotRow({ snapshot, isRestoreBlocked, onCompare, onRestore, onDelete }: SnapshotRowProps) {
  const reasonId = useId();
  const isAuto = snapshot.kind === "auto_before_restore";

  return (
    <li className="flex min-h-14 items-center gap-3 border-b border-border py-2">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="flex min-w-0 items-center gap-2 text-sm">
          <span className="truncate font-medium">{snapshot.name}</span>
          {isAuto && (
            <span className="inline-flex shrink-0 items-center rounded-full border border-border px-2 py-0.5 text-badge font-medium text-muted-foreground">
              자동
            </span>
          )}
        </p>
        <p className="text-xs text-muted-foreground tabular-nums">{formatSnapshotTime(snapshot.createdAt)}</p>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`‘${snapshot.name}’ 버전 메뉴`}
            className="shrink-0 hover:bg-secondary aria-expanded:bg-secondary"
          >
            <MoreHorizontal aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-auto max-w-72">
          <DropdownMenuItem onSelect={onCompare}>
            <GitCompare aria-hidden />
            지금과 비교
          </DropdownMenuItem>
          <DropdownMenuItem
            aria-disabled={isRestoreBlocked}
            aria-describedby={isRestoreBlocked ? reasonId : undefined}
            className="aria-disabled:opacity-65"
            onSelect={(event) => {
              if (isRestoreBlocked) {
                event.preventDefault();
                return;
              }
              onRestore();
            }}
          >
            <RotateCcw aria-hidden />
            되돌리기
          </DropdownMenuItem>
          {isRestoreBlocked && (
            <DropdownMenuLabel id={reasonId} className="text-xs font-normal break-keep text-muted-foreground">
              {RESTORE_BLOCKED_REASON}
            </DropdownMenuLabel>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={onDelete}>
            <Trash2 aria-hidden />
            지우기
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  );
}
