import { z } from "zod";

import {
  isChatRoutingLane,
  isPromptSetModelId,
  type AdminPromptRouteAllowedPair,
  type AdminPromptRouteCell,
  type AdminPromptRouteRow,
  type AdminPromptRoutingResponse,
  type RoomModel,
  type RoutingLane,
  type RoutingStage,
} from "@/entities/prompt-routing";

/** 저장·되돌리기의 범위. 채팅 두 레인은 기존 경로로 함께, 소설 레인은 소설 경로로 따로 저장한다 — 한 저장이 다른 범위의
 * 행을 싣지 않는다(서버는 기존 경로에 실려 온 소설 행을 버리고, 소설 경로에 실려 온 채팅 행은 거부한다). */
export type RoutingScope = "chat" | "novel";

export function scopeOfLane(lane: RoutingLane): RoutingScope {
  return isChatRoutingLane(lane) ? "chat" : "novel";
}

export const ROUTING_SCOPE_LABELS = {
  chat: "채팅",
  novel: "소설",
} satisfies Record<RoutingScope, string>;

/** 폼 레코드의 키. 이 함수 하나로만 만든다. */
export type RouteCellKey = `${RoutingLane}|${RoomModel}|${RoutingStage}`;

export function routeCellKey(lane: RoutingLane, roomModel: RoomModel, stage: RoutingStage): RouteCellKey {
  return `${lane}|${roomModel}|${stage}`;
}

export function cellKeyOf(cell: Pick<AdminPromptRouteCell, "lane" | "roomModel" | "stage">): RouteCellKey {
  return routeCellKey(cell.lane, cell.roomModel, cell.stage);
}

/** (부를 모델, 경로) 쌍의 셀렉트 값. 목록은 서버의 `allowedPairs` 에서 만들고 저장할 때 그 목록에서 다시 찾는다. */
export function pairValue(pair: Pick<AdminPromptRouteAllowedPair, "model" | "backend">): string {
  return `${pair.model}@${pair.backend}`;
}

/** 칸 하나: 행이 없으면(env 기본값을 따른다) `env`, 있으면 고른 쌍과 읽을 체인. 생성 단계는 늘 방 모델의 체인을 읽어
 * `chainModel` 이 null 이다. */
const cellFormSchema = z.discriminatedUnion("mode", [
  z.object({ mode: z.literal("env") }),
  z.object({
    mode: z.literal("row"),
    pair: z.string(),
    chainModel: z.string().refine(isPromptSetModelId).nullable(),
  }),
]);

export type RouteCellForm = z.infer<typeof cellFormSchema>;

export type RoutingFormValues = { cells: Partial<Record<RouteCellKey, RouteCellForm>> };

/** 쌍이 서버 목록에 없거나(화면을 연 뒤 목록이 바뀐 경우) 그 칸의 단계 종류가 고를 수 없는 쌍이거나 판정 칸에 체인이
 * 비면 그 칸의 오류다. 목록이 응답에 있어 스키마를 응답마다 만든다. */
export function buildRoutingFormSchema(data: AdminPromptRoutingResponse) {
  const kindByKey = new Map<string, AdminPromptRouteCell["kind"]>(data.cells.map((cell) => [cellKeyOf(cell), cell.kind]));
  return z
    .object({ cells: z.record(z.string(), cellFormSchema) })
    .superRefine((values, ctx) => {
      for (const [key, cell] of Object.entries(values.cells)) {
        if (cell.mode !== "row") continue;
        const kind = kindByKey.get(key);
        if (!data.allowedPairs.some((pair) => pairValue(pair) === cell.pair && pair.kind === kind)) {
          ctx.addIssue({ code: "custom", path: ["cells", key], message: "고를 수 없는 모델·경로예요." });
        } else if (kind === "structured" && cell.chainModel === null) {
          ctx.addIssue({ code: "custom", path: ["cells", key], message: "읽을 체인을 고르세요." });
        }
      }
    });
}

/** `effective` 로 채우지 않는다 — 그러면 env 가 정한 값이 행으로 저장돼 빈 칸이 사라진다. 그 칸 자신의 행(`configured`)만 읽는다. */
export function serverToForm(data: AdminPromptRoutingResponse): RoutingFormValues {
  const cells: RoutingFormValues["cells"] = {};
  for (const cell of data.cells) {
    const row = cell.configured;
    cells[cellKeyOf(cell)] =
      row === null
        ? { mode: "env" }
        : { mode: "row", pair: pairValue({ model: row.callModel, backend: row.backend }), chainModel: row.chainModel };
  }
  return { cells };
}

/** 그 범위의 칸 중 행이 있는 칸만 펼친다. 쌍은 서버 목록에서 다시 찾아 좁힌다(스키마가 이미 목록 밖 쌍을 막았다). */
export function formToServer(
  values: RoutingFormValues,
  data: AdminPromptRoutingResponse,
  scope: RoutingScope,
): AdminPromptRouteRow[] {
  return data.cells.flatMap((cell) => {
    if (scopeOfLane(cell.lane) !== scope) return [];
    const form = values.cells[cellKeyOf(cell)];
    if (form?.mode !== "row") return [];
    const pair = data.allowedPairs.find((p) => pairValue(p) === form.pair);
    if (pair === undefined) return [];
    return [
      {
        lane: cell.lane,
        roomModel: cell.roomModel,
        stage: cell.stage,
        chainModel: form.chainModel,
        callModel: pair.model,
        backend: pair.backend,
      },
    ];
  });
}

export function isSameCellForm(a: RouteCellForm | undefined, b: RouteCellForm | undefined): boolean {
  if (a === undefined || b === undefined) return a === b;
  if (a.mode === "env" || b.mode === "env") return a.mode === b.mode;
  return a.pair === b.pair && a.chainModel === b.chainModel;
}

/** 서버가 문자열로 준 칸(422 의 `row`)을 지금 표의 키로 좁히는 사상. */
export function cellKeyMap(data: AdminPromptRoutingResponse): Map<string, RouteCellKey> {
  return new Map(
    data.cells.map((cell) => {
      const key = cellKeyOf(cell);
      return [key, key];
    }),
  );
}
