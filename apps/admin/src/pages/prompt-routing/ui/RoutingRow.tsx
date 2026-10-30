import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ai-character-chat/ui/components/select";
import { TableCell, TableRow } from "@ai-character-chat/ui/components/table";
import { Controller, useFormContext, useWatch } from "react-hook-form";

import {
  isChatRoutingLane,
  isNovelPromptModel,
  isPromptSetModelId,
  isRoomLive,
  PROMPT_MODEL_LABELS,
  ROUTING_LANE_LABELS,
  ROUTING_STAGE_LABELS,
  type AdminPromptRouteCell,
  type AdminPromptRoutingResponse,
  type PromptSetModelId,
  type RoutingLane,
} from "@/entities/prompt-routing";

import {
  candidateCalls,
  costRatioText,
  findPair,
  formatPrice,
  chainCallMismatchText,
  generationChainText,
  pairLabel,
  roomModelLabel,
  selectablePairs,
} from "../model/describe";
import {
  cellKeyOf,
  isSameCellForm,
  pairValue,
  routeCellKey,
  type RouteCellForm,
  type RoutingFormValues,
} from "../model/schema";
import { PROBLEM_BADGE_CLASS } from "./badgeClasses";
import { LivePriceCell, LiveRouteCell } from "./LiveRouteCell";

const ENV_VALUE = "env";
/** 읽을 체인은 판정·요약 행만 고른다. Haiku 글쓰기 체인은 빠진다 — 그 체인의 판정·요약 문안은 게시 검증을 맞추려고 둔 사본이라
 * 서버가 그 체인을 고른 행을 거부한다. */
const CHAIN_MODELS = Object.keys(PROMPT_MODEL_LABELS)
  .filter(isPromptSetModelId)
  .filter((model) => model !== "haiku_writer");
/** 소설 레인에는 소설에서 고를 수 있는 모델의 체인만 있다 — 서버가 다른 체인을 고른 행을 거부한다. */
const NOVEL_CHAIN_MODELS = CHAIN_MODELS.filter(isNovelPromptModel);

function chainModelsFor(lane: RoutingLane): readonly PromptSetModelId[] {
  return lane === "novel" ? NOVEL_CHAIN_MODELS : CHAIN_MODELS;
}

/** 오류 요약의 항목이 그 칸으로 포커스를 옮길 때 찾는 id. */
export function pairSelectId(cell: Pick<AdminPromptRouteCell, "lane" | "roomModel" | "stage">) {
  return `route-${cellKeyOf(cell)}-pair`;
}

type RoutingRowProps = {
  cell: AdminPromptRouteCell;
  data: AdminPromptRoutingResponse;
  /** 같은 단계의 두 방 행 중 첫 행이면 단계 이름을 보인다(둘째 행은 보이는 글자 없이 접근 이름만). */
  showsStage: boolean;
  /** 마지막 저장 상태의 이 칸 — 바뀐 행 표시의 기준. */
  saved: RouteCellForm | undefined;
};

export function RoutingRow({ cell, data, showsStage, saved }: RoutingRowProps) {
  const key = cellKeyOf(cell);
  const {
    control,
    clearErrors,
    formState: { errors },
  } = useFormContext<RoutingFormValues>();
  const value = useWatch({ control, name: `cells.${key}` });
  // 장면 헤더는 자기 행이 없으면 같은 방의 스탯 판정 행을 물려받는다 — 저장 전 미리보기라 폼 값으로 그린다(저장된 상태의
  // 물려받음은 운영 값 칸이 서버 해석으로 따로 보인다).
  const statValue = useWatch({ control, name: `cells.${routeCellKey(cell.lane, cell.roomModel, "stat_judgment")}` });
  const error = errors.cells?.[key]?.message;
  const errorId = `route-${key}-error`;
  const isChanged = !isSameCellForm(value, saved);
  const roomLabel = roomModelLabel(cell.lane, cell.roomModel);
  const rowName = `${ROUTING_LANE_LABELS[cell.lane]} ${roomLabel} ${ROUTING_STAGE_LABELS[cell.stage]}`;
  const isGeneration = cell.kind === "generation";
  const isNovel = cell.lane === "novel";
  // 소설 생성 단계는 이 표를 읽지 않는다 — 체인·부를 모델이 늘 작업 모델이고 경로는 env 배정을 따른다. 고를 것이 없어 보이기만
  // 한다(지금 운영 값 칸이 env 로 푼 경로를 보인다).
  const isDisplayOnly = isNovel && isGeneration;
  const pickedCalls = value?.mode === "row" && isChanged ? candidateCalls(cell, value.pair) : undefined;
  const mismatch = chainCallMismatchText(cell, value, data);
  // 소설 구조화 칸은 고른 쌍의 원가 배수와 지금 env 로 운영에서 건너뛸지를 저장 전에 보인다(서버가 후보마다 계산한 값).
  const pickedCandidate =
    isNovel && value?.mode === "row" ? cell.candidates.find((candidate) => pairValue(candidate) === value.pair) : undefined;
  const pickedCost = pickedCandidate === undefined ? null : costRatioText(pickedCandidate);

  return (
    <>
      <TableRow>
        <th scope="row" className="p-2 text-left align-top font-medium whitespace-nowrap text-foreground">
          <span className="inline-flex items-start gap-1.5">
            {/* 바뀐 행은 색이 아니라 모양으로 — card 위 채움만으로는 3:1 이 안 나온다. 자리를 늘 비워 열 폭이 흔들리지 않게 한다. */}
            <span aria-hidden className={isChanged ? "text-foreground" : "invisible"}>
              ●
            </span>
            <span className={showsStage ? undefined : "sr-only"}>{ROUTING_STAGE_LABELS[cell.stage]}</span>
            <span className="sr-only">
              {" "}
              · {roomLabel}
              {isChanged && ", 저장 안 함"}
            </span>
          </span>
        </th>
        <TableCell className="align-top text-muted-foreground">
          {roomLabel}
          {isChatRoutingLane(cell.lane) && !isRoomLive(data, cell.roomModel) && (
            <span className="block text-xs">지금 안 읽힘</span>
          )}
        </TableCell>
        <TableCell className="align-top">
          {isDisplayOnly ? (
            <div className="flex w-60 flex-col gap-1 whitespace-normal">
              <span className="text-foreground">작업 모델로 불러요</span>
              <span className="break-keep text-xs text-muted-foreground">
                이 표로 바꾸지 않아요 — 경로는 env 배정을 따라요
              </span>
            </div>
          ) : (
          <div className="flex w-60 flex-col gap-1 whitespace-normal">
            <Controller
              control={control}
              name={`cells.${key}`}
              render={({ field }) => (
                <Select
                  value={field.value?.mode === "row" ? field.value.pair : ENV_VALUE}
                  onValueChange={(next) => {
                    clearErrors(`cells.${key}`);
                    field.onChange(nextCellForm(cell, data, field.value, next));
                  }}
                >
                  <SelectTrigger
                    ref={field.ref}
                    id={pairSelectId(cell)}
                    className="w-full"
                    aria-label={`${rowName} 부를 모델·경로`}
                    aria-invalid={error !== undefined}
                    aria-describedby={error === undefined ? undefined : errorId}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ENV_VALUE}>env 기본값 따름</SelectItem>
                    {selectablePairs(cell).map((pair) => (
                      <SelectItem key={pairValue(pair)} value={pairValue(pair)}>
                        {pairLabel(pair)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {isGeneration && (
              <span className="text-xs text-muted-foreground">방 모델로 불러요 — 경로만 고를 수 있어요</span>
            )}
            {pickedCalls?.[0] !== undefined && (
              <span className="text-xs text-muted-foreground tabular-nums">
                고른 값: {pickedCalls[0].modelId} ·{" "}
                {pickedCalls[0].price === null ? "단가 표에 없음" : formatPrice(pickedCalls[0].price)}
              </span>
            )}
            {cell.stage === "scene_judgment" && value?.mode === "env" && statValue?.mode === "row" && (
              <span className="text-xs text-muted-foreground">스탯 판정 행을 따라요</span>
            )}
            {mismatch !== null && <span className="break-keep text-xs text-muted-foreground">{mismatch}</span>}
            {pickedCost !== null && <span className="break-keep text-xs text-muted-foreground">{pickedCost}</span>}
            {pickedCandidate?.skippedNow != null && (
              <span className="flex flex-col items-start gap-1 text-xs text-muted-foreground">
                <span className={PROBLEM_BADGE_CLASS}>지금 운영에서는 건너뜀</span>
                <span className="break-keep">{pickedCandidate.skippedNow.message}</span>
              </span>
            )}
          </div>
          )}
        </TableCell>
        <TableCell className="align-top">
          <ChainField cell={cell} value={value} rowName={rowName} errorId={error === undefined ? undefined : errorId} />
        </TableCell>
        <TableCell className="align-top">
          <LiveRouteCell cell={cell} />
        </TableCell>
        <TableCell className="align-top">
          <LivePriceCell cell={cell} />
        </TableCell>
      </TableRow>
      {error !== undefined && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={6} className="pt-0">
            <p id={errorId} className="text-sm text-destructive-text">
              {error}
            </p>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

/** 쌍을 바꿀 때 체인: 생성 단계는 늘 없음, 판정 단계는 이미 행이었으면 고른 체인을 지키고 env 에서 처음 행으로 바꿀 때는 고른
 * 부를 모델과 같은 체인(가장 흔한 뜻)이다. */
function nextCellForm(
  cell: AdminPromptRouteCell,
  data: AdminPromptRoutingResponse,
  current: RouteCellForm | undefined,
  next: string,
): RouteCellForm {
  if (next === ENV_VALUE) return { mode: "env" };
  if (cell.kind === "generation") return { mode: "row", pair: next, chainModel: null };
  if (current?.mode === "row" && current.chainModel !== null) return { mode: "row", pair: next, chainModel: current.chainModel };
  // 부를 모델의 체인이 그 레인에 없으면(소설 레인의 판정 전용 모델) 기본 체인인 Gemini 로 시작한다.
  const callModel = findPair(data, next)?.model;
  if (callModel === undefined) return { mode: "row", pair: next, chainModel: null };
  return { mode: "row", pair: next, chainModel: chainModelsFor(cell.lane).includes(callModel) ? callModel : "gemini" };
}

type ChainFieldProps = {
  cell: AdminPromptRouteCell;
  value: RouteCellForm | undefined;
  rowName: string;
  errorId: string | undefined;
};

/** 부를 모델·경로 셀렉트가 칸 값의 `Controller` 를 쥐고 있어, 체인은 같은 값을 `setValue` 로 바꾼다(한 이름에 `Controller` 를 둘
 * 두지 않는다). */
function ChainField({ cell, value, rowName, errorId }: ChainFieldProps) {
  const { setValue, clearErrors } = useFormContext<RoutingFormValues>();
  const key = cellKeyOf(cell);

  if (cell.kind === "generation") {
    return <span className="text-muted-foreground">{generationChainText(cell.lane)}</span>;
  }
  if (value?.mode !== "row") {
    return (
      <span className="text-muted-foreground">
        <span aria-hidden>—</span>
        <span className="sr-only">env 기본값이 정해요</span>
      </span>
    );
  }

  return (
    <Select
      value={value.chainModel ?? undefined}
      onValueChange={(next) => {
        if (!isPromptSetModelId(next)) return;
        clearErrors(`cells.${key}`);
        setValue(`cells.${key}`, { ...value, chainModel: next }, { shouldDirty: true });
      }}
    >
      <SelectTrigger
        className="w-52"
        aria-label={`${rowName} 읽을 체인`}
        aria-invalid={errorId !== undefined}
        aria-describedby={errorId}
      >
        <SelectValue placeholder="체인을 고르세요" />
      </SelectTrigger>
      <SelectContent>
        {chainModelsFor(cell.lane).map((model) => (
          <SelectItem key={model} value={model}>
            {PROMPT_MODEL_LABELS[model]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
