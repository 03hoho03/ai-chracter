import type { MeResponse } from "@/entities/session";

/** 마이페이지의 본인인증 자리에 무엇을 둘지.
 *
 * 출석 보상은 게이트 스위치와 무관하게 늘 본인인증이 필요하고 출석판은 늘 열려 있어, 이 자리는 늘 보인다. 결제
 * 스위치는 가격 응답에서, 게이트 스위치와 정산은 세션에서 온다. 가격 응답을 아직 못 받았으면 결제는 꺼진 것으로 본다.
 *
 * 미인증 안내는 켜진 기능만 말한다 — 게이트가 꺼져 있으면 미션은 인증 없이도 받으므로 "받으려면 인증이 필요하다"가
 * 거짓이고, 정산이 꺼져 있으면 신청할 곳이 없다. 출석 보상은 언제나 말한다. */
export type IdentitySection = { kind: "verified" } | { kind: "unverified"; message: string };

/** 인증을 요구하는 기능 중 스위치로 켜고 끄는 것. */
export type IdentityFeatures = {
  payments: boolean;
  creatorPayout: boolean;
};

export function getIdentitySection(
  me: Pick<MeResponse, "identityVerified" | "identityGateEnabled">,
  features: IdentityFeatures,
): IdentitySection {
  if (me.identityVerified) return { kind: "verified" };
  return { kind: "unverified", message: unverifiedMessage(me.identityGateEnabled, features) };
}

/** 첫 문장은 켜진 기능을 "~하거나 ~하려면"으로 잇고, 둘째 문장은 나이 제한이 걸린 기능(구매·정산 신청)이 켜졌을 때만
 * 그 기능만 들어 말한다. 미션·출석은 나이 제한이 없어 둘째 문장에 넣지 않는다.
 *
 * 받는 조각은 게이트로 갈린다. 게이트가 꺼져 있으면 미션은 인증 없이 받으므로 미션을 말하지 않는다.
 *
 * 문장 조각은 어간과 끝 이음을 따로 둔다 — 받침에 따라 끝 이음이 갈린다("구매하려면" / "받으려면"). 가운데 이음 "거나"는
 * 받침과 무관하다. */
function unverifiedMessage(identityGateEnabled: boolean, features: IdentityFeatures): string {
  const receive = identityGateEnabled ? "매일 출석 클로버와 미션 클로버를 받" : "매일 출석 클로버를 받";
  const purposes = [
    features.payments && { stem: "클로버를 구매하", ending: "려면" },
    { stem: receive, ending: "으려면" },
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
