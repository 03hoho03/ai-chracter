import type { components } from "@ai-character-chat/api-types";

export type AdminPromptRoutingResponse = components["schemas"]["AdminPromptRoutingResponse"];
export type AdminPromptRouteCell = components["schemas"]["AdminPromptRouteCell"];
export type AdminPromptRouteCall = components["schemas"]["AdminPromptRouteCall"];
export type AdminPromptRouteCandidate = components["schemas"]["AdminPromptRouteCandidate"];
export type AdminPromptRoutePrice = components["schemas"]["AdminPromptRoutePrice"];
export type AdminPromptRouteAllowedPair = components["schemas"]["AdminPromptRouteAllowedPair"];
export type AdminPromptRouteRow = components["schemas"]["AdminPromptRouteRow"];
export type AdminPromptRouteChain = components["schemas"]["AdminPromptRouteChain"];

export type RoutingLane = AdminPromptRouteCell["lane"];
export type RoomModel = AdminPromptRouteCell["roomModel"];
export type RoutingStage = AdminPromptRouteCell["stage"];
/** 프롬프트 체인의 모델 축(판정 전용 `haiku` 포함). 배정 표의 읽을 체인·부를 모델과 프롬프트 화면의 모델 탭이 같은 값이다. */
export type PromptSetModelId = AdminPromptRouteRow["callModel"];
export type RouteBackend = AdminPromptRouteRow["backend"];
export type RouteSource = AdminPromptRouteCell["effective"]["source"];
export type RouteSkipReason = NonNullable<AdminPromptRouteCell["skipped"]>["reason"];
