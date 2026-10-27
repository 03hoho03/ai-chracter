import { Button } from "@ai-character-chat/ui/components/button";
import { Checkbox } from "@ai-character-chat/ui/components/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ai-character-chat/ui/components/dialog";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";

import { ContentListLoadMore } from "@/entities/content";
import {
  MyWorksSearchField,
  toWorkMemberKey,
  useMyWorksQuery,
  useWorkBundleMembersQuery,
  type WorkItem,
} from "@/entities/work";
import { describeAddWorksResult, useAddWorksToBundleMutation } from "@/features/manage-work-bundle";
import { createCallable } from "@/shared/lib/callable/createCallable";

import { resolveStudioEmptyResult } from "../model/studioBodyView";
import { toStudioWorkTitle } from "../model/studioWorkRow";
import { StudioTypeBadge } from "./StudioBadges";
import { StudioWorkThumbnail } from "./StudioWorkThumbnail";

type StudioAddWorksModalProps = {
  bundleId: string;
  bundleName: string;
};

/**
 * 묶음 화면의 "작품 넣기" — 내 작품 전체에서 여럿을 골라 이 묶음에 넣는다. 이미 든 작품은 체크된 채 잠겨 "이미 있음"으로
 * 보인다. 그 표시가 정확하도록 열 때 이 묶음의 작품을 끝까지 받고, 받기 전에는 목록을 그리지 않는다(반쯤 받은 집합으로
 * 그리면 뒤 페이지의 작품이 "안 넣음"으로 보인다).
 *
 * 넣기가 한도나 실패로 중간에 멈추면 이유를 푸터 위에 남기고 닫지 않는다 — 그때까지 넣은 작품은 "이미 있음"으로 바뀌어
 * 남은 것만 다시 보낼 수 있다. 행은 대화상자 면 위라 hover 채움이 `secondary` 다.
 */
export const StudioAddWorksModal = createCallable<StudioAddWorksModalProps>(({ call, bundleId, bundleName }) => {
  const [q, setQ] = useState<string | undefined>(undefined);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const errorId = useId();
  const worksQuery = useMyWorksQuery({ type: "all", status: "all", q });
  const membersQuery = useWorkBundleMembersQuery(bundleId);
  const mutation = useAddWorksToBundleMutation();
  const [selected, setSelected] = useState<ReadonlyMap<string, WorkItem>>(new Map());
  const [resultError, setResultError] = useState<string | undefined>(undefined);

  const members = membersQuery.data;
  const works = worksQuery.data?.pages.flatMap((page) => page.items) ?? [];
  // 그사이 다른 경로로 들어간 작품은 보낼 필요가 없다 — 고른 수에서도 뺀다.
  const toAdd = [...selected.entries()].filter(([key]) => members?.has(key) !== true).map(([, item]) => item);
  const isReady = members !== undefined && !worksQuery.isPending;
  const isFailed = membersQuery.isError || (worksQuery.isError && works.length === 0);
  const isSaving = mutation.isPending;

  function toggle(item: WorkItem, isChecked: boolean) {
    setResultError(undefined);
    setSelected((previous) => {
      const next = new Map(previous);
      const key = toWorkMemberKey(item.kind, item.id);
      if (isChecked) next.set(key, item);
      else next.delete(key);
      return next;
    });
  }

  function submit() {
    if (isSaving || toAdd.length === 0) return;
    setResultError(undefined);
    mutation.mutate(
      { bundleId, works: toAdd.map((item) => ({ kind: item.kind, id: item.id })) },
      {
        onSuccess: (result) => {
          // 넣을 수 없던 작품은 목록에서도 곧 사라진다 — 고른 채 남기면 보이지 않는 선택이 "n개 넣기"에 남는다.
          if (result.goneWorks.length > 0) {
            setSelected((previous) => {
              const next = new Map(previous);
              for (const work of result.goneWorks) next.delete(toWorkMemberKey(work.kind, work.id));
              return next;
            });
          }
          const description = describeAddWorksResult(result);
          if (description === null) return;
          if (description.tone === "success") {
            toast.success(description.message);
            call.end();
            return;
          }
          if (result.stoppedBy === "bundleGone") {
            toast.error(description.message);
            call.end();
            return;
          }
          setResultError(description.message);
        },
        // 재동의로 멈춘 경우만 실패로 끝난다 — 전역 재동의 모달이 뜨므로 이 대화상자는 닫는다.
        onError: () => call.end(),
      },
    );
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="break-keep [overflow-wrap:anywhere]">‘{bundleName}’에 작품 넣기</DialogTitle>
          <DialogDescription>넣을 작품을 골라 주세요. 이미 든 작품은 체크돼 있어요.</DialogDescription>
        </DialogHeader>
        <MyWorksSearchField inputRef={searchInputRef} query={q} onQueryChange={setQ} className="shrink-0" />

        <DialogBody scrollLabel="넣을 작품 목록" className="flex flex-col gap-2">
          {isFailed && (
            <div role="alert" className="flex flex-col items-center gap-3 py-8 text-center">
              <p className="text-sm text-destructive-text">작품을 불러오지 못했어요.</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  if (membersQuery.isError) void membersQuery.refetch();
                  if (worksQuery.isError) void worksQuery.refetch();
                }}
              >
                다시 시도
              </Button>
            </div>
          )}
          {!isFailed && !isReady && <AddWorksSkeleton />}
          {!isFailed && isReady && works.length === 0 && (
            <p className="py-8 text-center text-sm break-keep text-muted-foreground">
              {q === undefined ? "아직 만든 작품이 없어요." : resolveStudioEmptyResult({ q, filterLabel: undefined }).message}
            </p>
          )}
          {!isFailed && isReady && works.length > 0 && (
            <>
              <ul
                ref={listRef}
                tabIndex={-1}
                aria-busy={worksQuery.isPlaceholderData}
                className="flex flex-col gap-1 outline-none"
              >
                {works.map((item) => {
                  const key = toWorkMemberKey(item.kind, item.id);
                  return (
                    <li key={key}>
                      <AddWorkRow
                        item={item}
                        isMember={members.has(key)}
                        isChecked={members.has(key) || selected.has(key)}
                        onCheckedChange={(isChecked) => toggle(item, isChecked)}
                      />
                    </li>
                  );
                })}
              </ul>
              <ContentListLoadMore
                hasMore={worksQuery.hasNextPage}
                isLoading={worksQuery.isFetchingNextPage}
                onLoadMore={() => {
                  if (worksQuery.hasNextPage && !worksQuery.isFetchingNextPage) void worksQuery.fetchNextPage();
                }}
                onExhausted={() => listRef.current?.focus()}
              />
            </>
          )}
        </DialogBody>

        {resultError !== undefined && (
          <p id={errorId} role="alert" className="shrink-0 text-sm break-keep text-destructive-text">
            {resultError}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => call.end()}>
            취소
          </Button>
          <Button
            type="button"
            aria-disabled={isSaving || toAdd.length === 0}
            aria-describedby={resultError !== undefined ? errorId : undefined}
            className="aria-disabled:opacity-65"
            onClick={submit}
          >
            {toSubmitLabel(isSaving, toAdd.length)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});

function toSubmitLabel(isSaving: boolean, count: number): string {
  if (isSaving) return "넣는 중…";
  return count === 0 ? "넣기" : `${count}개 넣기`;
}

type AddWorkRowProps = {
  item: WorkItem;
  isMember: boolean;
  isChecked: boolean;
  onCheckedChange: (isChecked: boolean) => void;
};

/** 고를 작품 한 줄. 줄 전체가 라벨이다. 이미 든 작품은 체크를 풀 수 없게 잠근다 — 빼기는 묶음 화면의 행 메뉴가 맡는다
 * (여기서 풀어도 아무것도 보내지 않으면 "뺐다"로 오해한다). 잠금은 `aria-disabled` 라 Tab 순서에 남아 "이미 있음"이 읽힌다. */
function AddWorkRow({ item, isMember, isChecked, onCheckedChange }: AddWorkRowProps) {
  const checkboxId = useId();
  const noteId = useId();
  const title = toStudioWorkTitle(item);

  return (
    <label
      htmlFor={checkboxId}
      className={cn(
        "flex items-center gap-3 rounded-lg px-2 py-2",
        !isMember && "cursor-pointer motion-safe:transition-colors hover:bg-secondary",
      )}
    >
      <Checkbox
        id={checkboxId}
        checked={isChecked}
        aria-disabled={isMember}
        aria-describedby={isMember ? noteId : undefined}
        className="aria-disabled:opacity-65"
        onCheckedChange={(next) => {
          if (isMember) return;
          onCheckedChange(next === true);
        }}
      />
      <StudioWorkThumbnail item={item} className="size-10" />
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-sm font-medium break-keep text-foreground [overflow-wrap:anywhere]">{title}</span>
        <span className="flex flex-wrap items-center gap-1.5">
          <StudioTypeBadge kind={item.kind} />
          {isMember && (
            <span id={noteId} className="text-xs text-muted-foreground">
              이미 있음
            </span>
          )}
        </span>
      </span>
    </label>
  );
}

/** 진행 표시라 `motion-safe:` 를 붙이지 않는다. 면이 대화상자라 채움은 `secondary` 다. */
function AddWorksSkeleton() {
  return (
    <div role="status" aria-busy aria-label="작품 불러오는 중" className="flex flex-col gap-1">
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="flex items-center gap-3 px-2 py-2">
          <span className="size-4 animate-pulse rounded-[4px] bg-secondary" />
          <span className="size-10 animate-pulse rounded-lg bg-secondary" />
          <span className="h-4 w-1/3 animate-pulse rounded bg-secondary" />
        </div>
      ))}
    </div>
  );
}
