import type { components } from "@ai-character-chat/api-types";

import {
  ROOM_MODEL_LABELS,
  ROUTING_STAGE_LABELS,
  type AdminPromptRoutingResponse,
  type RoutingLane,
} from "@/entities/prompt-routing";

import { promptSectionLabel } from "./channels";
import type { PromptModel } from "./model";

type ChainReader = components["schemas"]["AdminPromptRouteChainReader"];

const ROOM_ORDER = Object.keys(ROOM_MODEL_LABELS);
const STAGE_ORDER = Object.keys(ROUTING_STAGE_LABELS);

/** 운영에서 이 체인을 읽는 칸(방 → 단계 순). 판정은 배정 표 응답의 체인 목록에서 그 (레인, 모델) 하나를 찾는 것뿐이다 — 화면이
 * 칸을 다시 조합하지 않는다. 목록에 없으면 읽는 칸이 없다. */
export function chainReaders(
  routing: AdminPromptRoutingResponse,
  lane: RoutingLane,
  model: PromptModel,
): ChainReader[] {
  const chain = routing.chains.find((candidate) => candidate.lane === lane && candidate.model === model);
  if (!chain) return [];
  return [...chain.readBy].sort(
    (a, b) => ROOM_ORDER.indexOf(a.roomModel) - ROOM_ORDER.indexOf(b.roomModel) || STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage),
  );
}

/** "Opus 방 스탯 판정(스탯 규칙 판정)" 꼴. 괄호 안은 그 칸이 읽는 섹션들이다. */
export function describeReader(reader: ChainReader): string {
  const channels = reader.channels.map(promptSectionLabel).join("·");
  const cell = `${ROOM_MODEL_LABELS[reader.roomModel]} ${ROUTING_STAGE_LABELS[reader.stage]}`;
  return channels ? `${cell}(${channels})` : cell;
}
