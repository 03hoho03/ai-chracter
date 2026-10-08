import type { MeResponse } from "@/entities/session";

/** 마이페이지의 본인인증 자리에 무엇을 둘지.
 *
 * 본인인증을 요구하는 기능(결제·무료 대화 게이트)이 하나라도 켜져 있을 때만 보인다 — 쓰일 곳이 없는 인증으로 개인정보를
 * 받지 않는다(서버의 인증 시작도 같은 조건으로 막는다). 게이트만 먼저 켜는 순서로 배포해도 인증할 길이 있어야
 * 하므로 결제 스위치 하나만 보지 않는다. 결제 스위치는 가격 응답에서, 게이트 스위치는 세션에서 온다. 가격 응답을
 * 아직 못 받았으면 결제는 꺼진 것으로 본다.
 *
 * 미인증 안내는 켜진 기능만 말한다 — 게이트가 꺼져 있으면 무료 대화·출석·미션은 인증 없이도 되므로 "받으려면
 * 인증이 필요하다"가 거짓이다. */
export type IdentitySection = { kind: "hidden" } | { kind: "verified" } | { kind: "unverified"; message: string };

export function getIdentitySection(
  me: Pick<MeResponse, "identityVerified" | "identityGateEnabled">,
  paymentsEnabled: boolean,
): IdentitySection {
  if (!paymentsEnabled && !me.identityGateEnabled) return { kind: "hidden" };
  if (me.identityVerified) return { kind: "verified" };
  return { kind: "unverified", message: unverifiedMessage(me.identityGateEnabled, paymentsEnabled) };
}

function unverifiedMessage(identityGateEnabled: boolean, paymentsEnabled: boolean): string {
  if (identityGateEnabled && paymentsEnabled) {
    return "클로버를 구매하고 매일 무료 대화·출석·미션 클로버를 받으려면 휴대폰 본인인증이 필요해요.";
  }
  if (identityGateEnabled) return "매일 무료 대화·출석·미션 클로버를 받으려면 휴대폰 본인인증이 필요해요.";
  return "클로버를 구매하려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.";
}
