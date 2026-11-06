import type { components } from "@ai-character-chat/api-types";

export type AdminLlmCredential = components["schemas"]["AdminLlmCredential"];
export type AdminLlmCredentialCheckItem = components["schemas"]["AdminLlmCredentialCheckItem"];
export type AdminLlmCredentialCheckResponse = components["schemas"]["AdminLlmCredentialCheckResponse"];
export type AdminLlmCredentialListResponse = components["schemas"]["AdminLlmCredentialListResponse"];
export type AdminLlmCredentialSpend = components["schemas"]["AdminLlmCredentialSpend"];
export type AdminLlmCredentialCreateRequest = components["schemas"]["AdminLlmCredentialCreateRequest"];
export type AdminLlmCredentialUpdateRequest = components["schemas"]["AdminLlmCredentialUpdateRequest"];
export type AdminLlmCredentialSecretRequest = components["schemas"]["AdminLlmCredentialSecretRequest"];
export type AdminLlmCredentialOrderRequest = components["schemas"]["AdminLlmCredentialOrderRequest"];
export type AdminLlmCredentialPoolRequest = components["schemas"]["AdminLlmCredentialPoolRequest"];

/** 서버 스위치는 기능 스위치 조회의 읽기 전용 칸에서 읽는다. 그 화면의 타입 파일을 가져오지 않고 생성 타입에서 바로 쓴다 — page 끼리는
 * import 할 수 없다. */
export type AdminFeatureSwitchListResponse = components["schemas"]["AdminFeatureSwitchListResponse"];

/** 모델 축. 서버 이름 목록이 단일 소스라 생성 타입에서 꺼낸다. */
export type ClaudeModelAxis = AdminLlmCredentialCheckItem["modelAxis"];
export type CheckErrorKind = NonNullable<AdminLlmCredentialCheckItem["errorKind"]>;
export type EnableBlocker = NonNullable<AdminLlmCredential["enableBlocker"]>;
export type CredentialState = AdminLlmCredential["state"];
export type CredentialStateReason = NonNullable<AdminLlmCredential["stateReason"]>;
export type CredentialProvider = AdminLlmCredential["provider"];
