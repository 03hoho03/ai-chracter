import type { MeResponse } from "@/entities/session";

/** 마이페이지의 본인인증 자리에 무엇을 둘지.
 *
 * 본인인증을 요구하는 기능(결제·무료 대화 게이트·크리에이터 정산)이 하나라도 켜져 있을 때만 보인다 — 쓰일 곳이 없는
 * 인증으로 개인정보를 받지 않는다(서버의 인증 시작도 같은 조건으로 막는다). 어느 하나만 먼저 켜는 순서로 배포해도
 * 인증할 길이 있어야 하므로 한 스위치만 보지 않는다. 결제 스위치는 가격 응답에서, 게이트 스위치와 정산은 세션에서
 * 온다. 가격 응답을 아직 못 받았으면 결제는 꺼진 것으로 본다.
 *
 * 미인증 안내는 켜진 기능만 말한다 — 게이트가 꺼져 있으면 무료 대화·미션은 인증 없이도 되므로 "받으려면 인증이
 * 필요하다"가 거짓이고, 정산이 꺼져 있으면 신청할 곳이 없다. */
export type IdentitySection = { kind: "hidden" } | { kind: "verified" } | { kind: "unverified"; message: string };

/** 인증을 요구하는 기능 중 켜진 것. */
export type IdentityFeatures = {
  payments: boolean;
  creatorPayout: boolean;
};

export function getIdentitySection(
  me: Pick<MeResponse, "identityVerified" | "identityGateEnabled">,
  features: IdentityFeatures,
): IdentitySection {
  if (!features.payments && !me.identityGateEnabled && !features.creatorPayout) return { kind: "hidden" };
  if (me.identityVerified) return { kind: "verified" };
  return { kind: "unverified", message: unverifiedMessage(me.identityGateEnabled, features) };
}

/** 첫 문장은 켜진 기능을 "~하거나 ~하려면"으로 잇고, 둘째 문장은 나이 제한이 걸린 기능(구매·정산 신청)이 켜졌을 때만
 * 그 기능만 들어 말한다. 무료 대화·미션은 나이 제한이 없어 둘째 문장에 넣지 않는다.
 *
 * 문장 조각은 어간과 끝 이음을 따로 둔다 — 받침에 따라 끝 이음이 갈린다("구매하려면" / "받으려면"). 가운데 이음 "거나"는
 * 받침과 무관하다. */
function unverifiedMessage(identityGateEnabled: boolean, features: IdentityFeatures): string {
  const purposes = [
    features.payments && { stem: "클로버를 구매하", ending: "려면" },
    identityGateEnabled && { stem: "매일 무료 대화와 미션 클로버를 받", ending: "으려면" },
    features.creatorPayout && { stem: "크리에이터 정산을 신청하", ending: "려면" },
  ].filter((purpose) => purpose !== false);

  const clause = purposes
    .map((purpose, index) => purpose.stem + (index === purposes.length - 1 ? purpose.ending : "거나"))
    .join(" ");
  const first = `${clause} 휴대폰 본인인증이 필요해요.`;

  if (features.payments && features.creatorPayout) {
    return `${first} 클로버 구매와 정산 신청은 만 19세 이상만 할 수 있어요.`;
  }
  if (features.payments) return `${first} 만 19세 이상만 구매할 수 있어요.`;
  if (features.creatorPayout) return `${first} 만 19세 이상만 신청할 수 있어요.`;
  return first;
}
