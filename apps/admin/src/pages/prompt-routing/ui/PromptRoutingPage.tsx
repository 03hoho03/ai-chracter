import { Button } from "@ai-character-chat/ui/components/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@ai-character-chat/ui/components/tabs";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";

import {
  isRoutingLane,
  promptRoutingKeys,
  ROUTING_LANE_LABELS,
  routingQueryOptions,
  useRoutingQuery,
  type AdminPromptRouteCell,
  type AdminPromptRoutingResponse,
  type RoutingLane,
} from "@/entities/prompt-routing";
import { useDocumentTitle } from "@/shared/lib/useDocumentTitle";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";
import { QueryState } from "@/shared/ui/QueryState";
import { RESTING_DISABLED_PRIMARY_CLASS } from "@/shared/ui/restingDisabledPrimaryClass";
import { UnsavedChangesGuard } from "@/shared/ui/UnsavedChangesGuard";

import type { AdminPromptRouteRevisionSummary } from "../api/useRevisionListQuery";
import { chainCallMismatchText } from "../model/describe";
import type { RoutingOutcome } from "../model/outcome";
import {
  buildRoutingFormSchema,
  cellKeyOf,
  formToServer,
  isSameCellForm,
  serverToForm,
  type RouteCellKey,
  type RoutingFormValues,
} from "../model/schema";
import { DiscardEditsDialog } from "./DiscardEditsDialog";
import { RouteErrorSummary, type RouteFailureNotice } from "./RouteErrorSummary";
import { RoutingLaneTable } from "./RoutingLaneTable";
import { pairSelectId } from "./RoutingRow";
import { RoutingRevisionSection } from "./RoutingRevisionSection";
import { SaveRoutingDialog, type RoutingChange } from "./SaveRoutingDialog";

const LANES: readonly RoutingLane[] = ["story", "character"];

export function PromptRoutingPage() {
  useDocumentTitle("모델 배정");
  const routingQuery = useRoutingQuery();

  return (
    <PageContainer>
      <PageHeader title="모델 배정" />
      <div className="flex max-w-prose flex-col gap-2 text-sm text-muted-foreground">
        <p className="break-keep">
          채팅 두 레인의 단계마다 어느 프롬프트 체인을 읽고 어느 모델·경로로 부를지 정해요. 행이 없는 칸은 env 기본값을
          따르고, 표를 비우면 전부 env 로 돌아가요.
        </p>
        <ul className="flex list-disc flex-col gap-1 pl-5">
          <li className="break-keep">
            Claude 직결 행은 그 단계의 env 판정 모델이 Claude 인 동안에만 저장할 수 있어요. env 가 바뀌어 경로가 달라지면 그
            행은 "적용 안 됨"이 되고 env 값으로 돌아가요. "적용 안 됨" 행이 남아 있으면 그 칸을 env 기본값으로 돌려야 표를
            저장할 수 있어요.
          </li>
          <li className="break-keep">
            응답 생성 칸은 방 모델로만 부르고(대화 차감이 방 모델 단가예요) 경로만 고를 수 있어요.
          </li>
          <li className="break-keep">장면 헤더는 자기 행이 없으면 같은 방의 스탯 판정 행을 따라요.</li>
          <li className="break-keep">
            기억 인상 호출은 이 표 밖이라 env 설정만 따르고, 소설·심사 레인도 이 표를 따르지 않아요.
          </li>
        </ul>
      </div>
      <QueryState query={routingQuery} errorMessage="모델 배정 표를 불러오지 못했어요.">
        {(data) => <RoutingEditor data={data} />}
      </QueryState>
    </PageContainer>
  );
}

type RoutingEditorProps = {
  data: AdminPromptRoutingResponse;
};

/** 폼은 화면이 마지막으로 받아들인 표(`shown`)에서 만든다. 편집 중에 다른 곳의 저장으로 표 쿼리가 다시 오면 그대로 받아들이지
 * 않는다 — 받아들이면 폼이 새 값으로 다시 맞춰져 편집이 소리 없이 사라지고, 기준 이력도 새 것이 되어 다른 저장을 덮어쓸 수
 * 있다. 그 경우는 저장이 낡은 이력(409)으로 막히고 운영자가 "최신 표 불러오기"로 직접 바꾼다. 편집이 없을 때는 바로 따른다. */
function RoutingEditor({ data }: RoutingEditorProps) {
  const queryClient = useQueryClient();
  const [shown, setShown] = useState(data);
  const [activeLane, setActiveLane] = useState<RoutingLane>("story");
  const [notice, setNotice] = useState<RouteFailureNotice | null>(null);
  const [isReloading, setIsReloading] = useState(false);

  // `values` 는 참조가 바뀔 때마다 폼을 다시 맞춘다 — 받아들인 표가 바뀔 때만 새 객체를 만든다.
  const saved = useMemo(() => serverToForm(shown), [shown]);
  const schema = useMemo(() => buildRoutingFormSchema(shown), [shown]);
  const form = useForm<RoutingFormValues>({ resolver: zodResolver(schema), values: saved });
  const isDirty = form.formState.isDirty;
  if (data !== shown && !isDirty) setShown(data);

  const current = useWatch({ control: form.control, name: "cells" });
  const cellByKey = useMemo(
    () => new Map<RouteCellKey, AdminPromptRouteCell>(shown.cells.map((cell) => [cellKeyOf(cell), cell])),
    [shown],
  );
  const changes: RoutingChange[] = shown.cells.flatMap((cell) => {
    const key = cellKeyOf(cell);
    const before = saved.cells[key];
    const after = current[key];
    return before === undefined || after === undefined || isSameCellForm(before, after) ? [] : [{ cell, before, after }];
  });
  const errorKeys = Object.keys(form.formState.errors.cells ?? {});
  const shownNotice = liveNotice(notice, errorKeys, cellByKey);
  const isAllEnv = shown.cells.every((cell) => current[cellKeyOf(cell)]?.mode !== "row");

  const accept = (next: AdminPromptRoutingResponse) => {
    setShown(next);
    // 받아들인 표가 같은 참조여도(다시 받은 값이 같을 때) 폼이 그 표로 돌아가게 한다.
    form.reset(serverToForm(next));
  };

  const handleOutcome = (outcome: RoutingOutcome, restoredNumber: number | null) => {
    if (outcome.status === "saved") {
      accept(outcome.data);
      setNotice(null);
      const savedAs = `r${outcome.data.revisionNumber ?? "?"}`;
      toast.success(restoredNumber === null ? `${savedAs} 으로 저장했어요.` : `r${restoredNumber} 의 표를 ${savedAs} 으로 되돌렸어요.`);
      return;
    }
    const { failure } = outcome;
    if (failure.kind === "not-found") {
      toast.error(failure.message);
      void queryClient.invalidateQueries({ queryKey: promptRoutingKeys.revisions() });
      return;
    }
    if (failure.kind === "stale") {
      setNotice({ kind: "stale", message: failure.message });
      return;
    }
    setNotice({ kind: "rules", items: failure.items, restoredNumber });
    // 되돌리기의 거부는 그 이력의 칸이라 지금 폼 값과 다르다 — 행 오류 줄 대신 요약에만 둔다.
    if (restoredNumber !== null) return;
    for (const item of failure.items) {
      if (item.key !== null) form.setError(`cells.${item.key}`, { type: "server", message: item.message });
    }
  };

  const openSave = form.handleSubmit(
    async (values) => {
      const rows = formToServer(values, shown);
      const mismatchCount = shown.cells.filter(
        (cell) => chainCallMismatchText(cell, values.cells[cellKeyOf(cell)], shown) !== null,
      ).length;
      const outcome = await SaveRoutingDialog.call({ data: shown, changes, rows, mismatchCount });
      if (outcome !== undefined) handleOutcome(outcome, null);
    },
    () => toast.error("입력값을 확인해주세요."),
  );

  const resetAllToEnv = () => {
    for (const cell of shown.cells) {
      form.setValue(`cells.${cellKeyOf(cell)}`, { mode: "env" }, { shouldDirty: true });
    }
    form.clearErrors();
  };

  const reloadLatest = async () => {
    if (isDirty && !(await DiscardEditsDialog.call({ dirtyCount: changes.length }))) return;
    setIsReloading(true);
    try {
      const fresh = await queryClient.fetchQuery({ ...routingQueryOptions, staleTime: 0 });
      void queryClient.invalidateQueries({ queryKey: promptRoutingKeys.revisions() });
      accept(fresh);
      setNotice(null);
    } catch {
      toast.error("최신 표를 불러오지 못했어요. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsReloading(false);
    }
  };

  const focusCell = (cell: AdminPromptRouteCell) => {
    // 숨은 탭 패널 안의 셀렉트는 포커스를 받지 못한다 — 탭을 먼저 그린 뒤 옮긴다.
    flushSync(() => setActiveLane(cell.lane));
    document.getElementById(pairSelectId(cell))?.focus();
  };

  return (
    <FormProvider {...form}>
      <section className="flex flex-col gap-4 rounded-xl border border-border bg-card p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-col gap-1">
            <h2 className="text-lg font-semibold text-foreground">배정 표</h2>
            <p className="text-xs text-muted-foreground">
              {shown.revisionNumber === null ? "아직 저장한 적 없음 — 모든 칸이 env 기본값" : `지금 표 r${shown.revisionNumber}`}
              {changes.length > 0 && ` · 저장 안 한 변경 ${changes.length}칸`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={isAllEnv} onClick={resetAllToEnv}>
              모든 칸 env 로
            </Button>
            <Button
              type="button"
              size="sm"
              className={RESTING_DISABLED_PRIMARY_CLASS}
              disabled={!isDirty}
              onClick={() => void openSave()}
            >
              저장…
            </Button>
          </div>
        </div>

        {shownNotice !== null && (
          <RouteErrorSummary
            notice={shownNotice}
            cellByKey={cellByKey}
            onFocusCell={focusCell}
            onReload={() => void reloadLatest()}
            isReloading={isReloading}
          />
        )}

        <p className="text-xs text-muted-foreground">
          {shown.revisionNumber === null
            ? "지금 운영 값은 env 설정으로 푼 값이에요."
            : `지금 운영 값은 마지막 저장(r${shown.revisionNumber}) 기준이에요 — 저장하기 전에는 바뀌지 않아요.`}
        </p>

        <Tabs
          value={activeLane}
          onValueChange={(value) => {
            if (isRoutingLane(value)) setActiveLane(value);
          }}
        >
          <div className="overflow-x-auto">
            <TabsList variant="line">
              {LANES.map((lane) => {
                const changeCount = changes.filter((change) => change.cell.lane === lane).length;
                const errorCount = errorKeys.filter((key) => key.startsWith(`${lane}|`)).length;
                return (
                  <TabsTrigger key={lane} value={lane}>
                    {ROUTING_LANE_LABELS[lane]}
                    {changeCount > 0 && ` · 변경 ${changeCount}`}
                    {errorCount > 0 && <span className="text-destructive-text"> · 오류 {errorCount}</span>}
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </div>
          {LANES.map((lane) => (
            // 폼 하나가 두 레인을 다 들고 있어 탭을 바꿔도 편집이 남아야 한다 — 숨기기만 한다. 패널 안의 셀렉트가 진입점이라
            // Tab 정지는 뺀다.
            <TabsContent
              key={lane}
              value={lane}
              forceMount
              tabIndex={-1}
              className="pt-4 data-[state=inactive]:hidden"
            >
              <RoutingLaneTable lane={lane} data={shown} saved={saved} />
            </TabsContent>
          ))}
        </Tabs>

        <p className="text-xs text-muted-foreground">
          단가는 USD / 1M 토큰, 기준일 {shown.pricesAsOf}. 단가 표에 없는 모델은 "단가 표에 없음"으로 보여요.
        </p>
      </section>

      <RoutingRevisionSection
        data={shown}
        dirtyCount={changes.length}
        onRestoreOutcome={(outcome: RoutingOutcome, revision: AdminPromptRouteRevisionSummary) =>
          handleOutcome(outcome, revision.number)
        }
      />

      <UnsavedChangesGuard isDirty={isDirty} />
    </FormProvider>
  );
}

/** 저장 거부 요약은 칸 오류와 같은 폼 오류에서 거른다 — 운영자가 칸을 고쳐 그 칸의 오류가 지워지면 요약에서도 빠지고, 다 빠지면
 * 요약도 사라진다. 칸에 걸 수 없는 항목(지금 표에 없는 칸)은 고칠 칸이 없어 남긴다. 되돌리기 거부는 그 이력의 칸이라 폼 오류로
 * 걸지 않으므로 받은 그대로 둔다. */
function liveNotice(
  notice: RouteFailureNotice | null,
  errorKeys: readonly string[],
  cellByKey: ReadonlyMap<RouteCellKey, AdminPromptRouteCell>,
): RouteFailureNotice | null {
  if (notice === null || notice.kind !== "rules" || notice.restoredNumber !== null) return notice;
  const items = notice.items.filter(
    (item) => item.key === null || !cellByKey.has(item.key) || errorKeys.includes(item.key),
  );
  return items.length === 0 ? null : { ...notice, items };
}
