import type { components } from "@ai-character-chat/api-types";

export type AdminFeatureSwitchListResponse = components["schemas"]["AdminFeatureSwitchListResponse"];
export type AdminAdjustableSwitch = components["schemas"]["AdminAdjustableSwitch"];
export type AdminReadOnlySwitch = components["schemas"]["AdminReadOnlySwitch"];
export type AdminUnknownOverride = components["schemas"]["AdminUnknownOverride"];
export type AdminFeatureSwitchChangeItem = components["schemas"]["AdminFeatureSwitchChangeItem"];
export type AdminFeatureSwitchChangeListResponse = components["schemas"]["AdminFeatureSwitchChangeListResponse"];
export type AdminFeatureSwitchChangeResult = components["schemas"]["AdminFeatureSwitchChangeResult"];

/** 어드민에서 켜고 끄는 스위치 이름. 서버 이름 목록이 단일 소스라 생성 타입에서 꺼낸다. */
export type FeatureSwitchName = AdminAdjustableSwitch["name"];
/** `.env` 로만 바꾸는 스위치 이름. */
export type ReadOnlyFeatureSwitchName = AdminReadOnlySwitch["name"];
export type ReadOnlySwitchReason = AdminReadOnlySwitch["reason"];
export type FeatureSwitchWarning = AdminFeatureSwitchChangeResult["warnings"][number];
