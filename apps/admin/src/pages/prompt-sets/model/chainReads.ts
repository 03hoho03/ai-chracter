import type { components } from "@ai-character-chat/api-types";

import {
  isRoomLive,
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

/** 이 체인을 읽도록 배정된 칸(방 → 단계 순)을 지금 운영에서 실행되는 칸(`live`)과 상위 모델 스위치가 꺼져 안 읽히는 칸
 * (`switchedOff`)으로 나눈다. 판정은 배정 표 응답의 체인 목록에서 그 (레인, 모델) 하나를 찾는 것뿐이다 — 화면이 칸을 다시
 * 조합하지 않는다. 목록에 없으면 둘 다 비었다. 게시 문구·탭 표지의 칸 수는 `live` 로 센다. */
export function chainReaders(
  routing: AdminPromptRoutingResponse,
  lane: RoutingLane,
  model: PromptModel,
): { live: ChainReader[]; switchedOff: ChainReader[] } {
  const chain = routing.chains.find((candidate) => candidate.lane === lane && candidate.model === model);
  const sorted = [...(chain?.readBy ?? [])].sort(
    (a, b) => ROOM_ORDER.indexOf(a.roomModel) - ROOM_ORDER.indexOf(b.roomModel) || STAGE_ORDER.indexOf(a.stage) - STAGE_ORDER.indexOf(b.stage),
  );
  return {
    live: sorted.filter((reader) => isRoomLive(routing, reader.roomModel)),
    switchedOff: sorted.filter((reader) => !isRoomLive(routing, reader.roomModel)),
  };
}

/** "Opus 방 스탯 판정(스탯 규칙 판정)" 꼴. 괄호 안은 그 칸이 읽는 섹션들이다. */
export function describeReader(reader: ChainReader): string {
  const channels = reader.channels.map(promptSectionLabel).join("·");
  const cell = `${ROOM_MODEL_LABELS[reader.roomModel]} ${ROUTING_STAGE_LABELS[reader.stage]}`;
  return channels ? `${cell}(${channels})` : cell;
}
