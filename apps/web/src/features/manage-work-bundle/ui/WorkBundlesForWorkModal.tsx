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
import { Plus } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { useWorkBundlesForWorkQuery, WORK_BUNDLE_MAX_COUNT, type WorkBundleSummary } from "@/entities/work";
import { createCallable } from "@/shared/lib/callable/createCallable";
import { koreanParticle } from "@/shared/lib/text/koreanParticle";

import {
  usePutWorkBundleItemMutation,
  useRemoveWorkBundleItemMutation,
  type WorkBundleItemRef,
} from "../api/workBundleMutations";
import { toWorkBundleActionError } from "../model/bundleActionError";
import { WorkBundleNameModal } from "./WorkBundleNameModal";

type WorkBundlesForWorkModalProps = {
  work: WorkBundleItemRef;
  /** 행에 보이는 제목 — 어느 작품을 넣는지 설명에 적는다. */
  title: string;
};

/**
 * 작품 하나를 어느 묶음에 넣을지. 묶음마다 이 작품이 들었는지가 체크로 보이고, 누르면 바로 넣거나 뺀다(저장 단계가 따로
 * 없다 — 행 하나가 쓰기 하나다). 아래 "새 묶음 만들기"는 묶음을 만들고 이 작품을 곧바로 넣는다.
 *
 * 누른 결과는 서버 응답을 기다리지 않고 체크에 먼저 반영하고, 실패하면 되돌린다. 목록 행은 대화상자 면(popover) 위라
 * hover 채움이 `secondary` 다 — `bg-muted` 는 같은 값이라 사라진다.
 */
export const WorkBundlesForWorkModal = createCallable<WorkBundlesForWorkModalProps>(({ call, work, title }) => {
  const query = useWorkBundlesForWorkQuery(work.kind, work.id);
  const putMutation = usePutWorkBundleItemMutation();
  const removeMutation = useRemoveWorkBundleItemMutation();
  const limitNoteId = useId();
  // 누른 뒤 서버가 받아들인 값(또는 아직 응답 전인 값). 서버 목록이 다시 오면 같은 값이 되므로 지우지 않아도 거짓이 아니다.
  const [checkedOverrides, setCheckedOverrides] = useState<ReadonlyMap<string, boolean>>(new Map());
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());

  const bundles = query.data?.items ?? [];
  const isAtBundleLimit = bundles.length >= WORK_BUNDLE_MAX_COUNT;

  function setOverride(bundleId: string, value: boolean | undefined) {
    setCheckedOverrides((previous) => {
      const next = new Map(previous);
      if (value === undefined) next.delete(bundleId);
      else next.set(bundleId, value);
      return next;
    });
  }

  function setBusy(bundleId: string, isBusy: boolean) {
    setBusyIds((previous) => {
      const next = new Set(previous);
      if (isBusy) next.add(bundleId);
      else next.delete(bundleId);
      return next;
    });
  }

  async function toggle(bundleId: string, shouldContain: boolean) {
    setOverride(bundleId, shouldContain);
    setBusy(bundleId, true);
    try {
      if (shouldContain) await putMutation.mutateAsync({ bundleId, work });
      else await removeMutation.mutateAsync({ bundleId, work });
    } catch (error) {
      setOverride(bundleId, undefined);
      const notice = toWorkBundleActionError(error, shouldContain ? "addItem" : "removeItem");
      if (notice === null) {
        call.end();
        return;
      }
      toast.error(notice.message);
    } finally {
      setBusy(bundleId, false);
    }
  }

  async function createAndAdd() {
    if (isAtBundleLimit) return;
    const bundleId = await WorkBundleNameModal.call({ mode: "create" });
    if (bundleId === null) return;
    await toggle(bundleId, true);
  }

  return (
    <Dialog open={!call.ended} onOpenChange={(isOpen) => !isOpen && call.end()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>묶음에 넣기</DialogTitle>
          <DialogDescription className="[overflow-wrap:anywhere]">
            ‘{title}’{koreanParticle(title, "을/를")} 넣을 묶음을 골라 주세요.
          </DialogDescription>
        </DialogHeader>

        <DialogBody scrollLabel="묶음 목록" className="flex flex-col gap-1">
          {query.isPending && <BundleListSkeleton />}
          {query.isError && bundles.length === 0 && (
            <div role="alert" className="flex flex-col items-center gap-3 py-8 text-center">
              <p className="text-sm text-destructive-text">묶음을 불러오지 못했어요.</p>
              <Button type="button" variant="outline" size="sm" onClick={() => void query.refetch()}>
                다시 시도
              </Button>
            </div>
          )}
          {query.isSuccess && bundles.length === 0 && (
            <p className="py-8 text-center text-sm break-keep text-muted-foreground">
              아직 묶음이 없어요. 아래에서 새 묶음을 만들면 이 작품을 바로 넣어요.
            </p>
          )}
          {bundles.length > 0 && (
            <ul className="flex flex-col gap-1">
              {bundles.map((bundle) => (
                <li key={bundle.id}>
                  <BundleCheckRow
                    bundle={bundle}
                    isChecked={checkedOverrides.get(bundle.id) ?? bundle.containsWork === true}
                    isBusy={busyIds.has(bundle.id)}
                    onCheckedChange={(next) => void toggle(bundle.id, next)}
                  />
                </li>
              ))}
            </ul>
          )}
        </DialogBody>

        <DialogFooter className="sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1">
            <Button
              type="button"
              variant="outline"
              aria-disabled={isAtBundleLimit || query.isPending}
              aria-describedby={isAtBundleLimit ? limitNoteId : undefined}
              className="aria-disabled:opacity-65"
              onClick={() => {
                if (query.isPending) return;
                void createAndAdd();
              }}
            >
              <Plus aria-hidden />새 묶음 만들기
            </Button>
            {isAtBundleLimit && (
              <p id={limitNoteId} className="text-xs break-keep text-muted-foreground">
                묶음은 {WORK_BUNDLE_MAX_COUNT}개까지 만들 수 있어요.
              </p>
            )}
          </div>
          <Button type="button" onClick={() => call.end()}>
            완료
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
});

type BundleCheckRowProps = {
  bundle: WorkBundleSummary;
  isChecked: boolean;
  isBusy: boolean;
  onCheckedChange: (next: boolean) => void;
};

/** 체크박스 하나와 이름·항목 수. 줄 전체가 라벨이라 어디를 눌러도 체크가 바뀐다. 응답을 기다리는 동안은 같은 줄을 다시
 * 눌러도 보내지 않는다(`aria-disabled` — `disabled` 면 포커스가 떨어진다). */
function BundleCheckRow({ bundle, isChecked, isBusy, onCheckedChange }: BundleCheckRowProps) {
  const checkboxId = useId();

  return (
    <label
      htmlFor={checkboxId}
      className="flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 py-2 motion-safe:transition-colors hover:bg-secondary"
    >
      <Checkbox
        id={checkboxId}
        checked={isChecked}
        aria-disabled={isBusy}
        onCheckedChange={(next) => {
          if (isBusy) return;
          onCheckedChange(next === true);
        }}
      />
      <span className="min-w-0 flex-1 text-sm break-keep text-foreground [overflow-wrap:anywhere]">{bundle.name}</span>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{bundle.itemCount}개</span>
    </label>
  );
}

function BundleListSkeleton() {
  return (
    <div role="status" aria-busy aria-label="묶음 불러오는 중" className="flex flex-col gap-1">
      {Array.from({ length: 3 }, (_, index) => (
        <div key={index} className="flex items-center gap-3 px-2 py-3">
          <span className="size-4 animate-pulse rounded-[4px] bg-secondary" />
          <span className="h-4 w-1/2 animate-pulse rounded bg-secondary" />
        </div>
      ))}
    </div>
  );
}
