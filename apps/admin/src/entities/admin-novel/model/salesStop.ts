import type { components } from "@ai-character-chat/api-types";

import { apiErrorCode } from "@/shared/lib/api/client";

/** 원작 작품을 닫을 때(이용제한·삭제) 그 작품으로 만든 노벨을 어떻게 할지. 서버는 칸을 빼면 `close`(닫고 환급)로 읽는다. */
export type DerivativeNovelsChoice = NonNullable<components["schemas"]["AdminContentActionRequest"]["derivativeNovels"]>;

/** 화면의 처음 선택은 판매 중단이다 — 원작 조치가 산 회원의 열람까지 끊는 것은 법적·안전상 불가피할 때만이라, 운영자가
 * 일부러 고르게 한다. 서버의 생략값(`close`)과 다르므로 스위치가 켜져 있으면 칸을 늘 싣는다(`toDerivativeNovelsField`). */
export const DERIVATIVE_NOVELS_DEFAULT: DerivativeNovelsChoice = "stop_sales";

export const DERIVATIVE_NOVELS_LEGEND = "이 작품으로 만든 노벨";

export const DERIVATIVE_NOVELS_OPTIONS: readonly { value: DerivativeNovelsChoice; label: string }[] = [
  { value: "stop_sales", label: "판매 중단" },
  { value: "close", label: "이용제한(열람 차단 + 자동 환급)" },
];

const DERIVATIVE_NOVELS_EFFECT: Record<DerivativeNovelsChoice, string> = {
  stop_sales: "이 작품으로 만든 노벨은 판매만 멈춰요. 산 회원은 계속 읽고, 쓴 클로버는 돌려드리지 않아요.",
  close: "이 작품으로 만든 노벨을 산 회원의 열람이 끝나고, 쓴 클로버를 자동으로 돌려드려요.",
};

/** 서버는 파생 노벨 자신의 판매 중단·이용제한 칸을 건드리지 않고 원작 상태로 가린다. 그래서 원작 이용제한을 풀면 노벨도 함께
 * 돌아온다 — 노벨 상세에서 풀 것이 없다는 것을 이용제한 때 함께 말한다. 삭제는 되돌릴 수 없어 이 문장이 없다. */
const DERIVATIVE_NOVELS_ON_LIFT: Record<DerivativeNovelsChoice, string> = {
  stop_sales: "노벨에 판매 중단이 따로 걸리지 않아 원작 이용제한을 풀면 다시 팔려요.",
  close: "노벨에 이용제한이 따로 걸리지 않아 원작 이용제한을 풀면 다시 열리고, 돌려받은 회원은 다시 사야 읽어요.",
};

/** 고른 값이 산 회원에게 하는 일. 확정 전에 고른 값 바로 아래에 보인다 — 환급 문장은 `close` 일 때만이다. */
export function derivativeNovelsNote(choice: DerivativeNovelsChoice, action: "restrict" | "delete"): string {
  const effect = DERIVATIVE_NOVELS_EFFECT[choice];
  return action === "restrict" ? `${effect} ${DERIVATIVE_NOVELS_ON_LIFT[choice]}` : effect;
}

/** 요청에 실을 `derivativeNovels`. 정책 스위치가 꺼져 있거나 작품을 닫는 조치(이용제한·삭제)가 아니면 싣지 않는다 — 꺼짐에서
 * 빼면 서버가 지금처럼 처리하고(환급도 없다), 닫지 않는 조치에서는 서버가 이 칸을 읽지 않는다. */
export function toDerivativeNovelsField(
  isPolicyOn: boolean,
  isClosing: boolean,
  choice: DerivativeNovelsChoice | undefined,
): DerivativeNovelsChoice | undefined {
  if (!isPolicyOn || !isClosing) return undefined;
  return choice ?? DERIVATIVE_NOVELS_DEFAULT;
}

/** 판매 중단을 골랐는데 그사이 정책 스위치가 꺼진 409. 판매 중단·재개 직접 조치, 노벨 신고의 판매 중단, 원작 조치의
 * 파생 노벨 판매 중단이 모두 이 코드다. */
export function isNovelSalesStopDisabled(error: unknown): boolean {
  return apiErrorCode(error) === "NOVEL_SALES_STOP_DISABLED";
}

/** 그 409 의 문장. 호출부는 세션(`/admin/me`)을 다시 받아 스위치 꺼짐 화면으로 돌린다. */
export const NOVEL_SALES_STOP_DISABLED_MESSAGE = {
  novel: "정책 스위치가 꺼져 있어 판매를 멈추거나 다시 열 수 없어요. 화면을 새로 불러왔어요.",
  novelReport: "정책 스위치가 꺼져 있어 판매 중단으로 처리할 수 없어요. 화면을 새로 불러왔으니 처리 방법을 다시 골라 주세요.",
  content: "정책 스위치가 꺼져 있어 노벨 판매만 멈출 수는 없어요. 화면을 새로 불러왔으니 다시 확인하고 확정해 주세요.",
} as const;
