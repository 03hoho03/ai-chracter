import type { MeResponse } from "@/entities/session";

/** 마이페이지의 본인인증 자리에 무엇을 둘지.
 *
 * 본인인증을 요구하는 기능(결제·무료 대화 게이트·크리에이터 정산·출석 보상)이 하나라도 켜져 있을 때만 보인다 — 쓰일
 * 곳이 없는 인증으로 개인정보를 받지 않는다. 결제·게이트·정산은 어느 하나만 먼저 켜도 인증할 길이 있어야 하므로 한
 * 스위치만 보지 않는다. 서버의 인증 시작은 이 가운데 결제·게이트·정산 셋만 보고 출석은 보지 않는다 — 출석만 켜진
 * 서버에서는 이 섹션이 보여도 인증을 시작할 수 없으므로, 출석판은 결제나 게이트가 켜진 뒤에 켠다. 결제·출석 스위치는
 * 가격 응답에서, 게이트 스위치와 정산은 세션에서 온다. 가격 응답을 아직 못 받았으면 둘 다 꺼진 것으로 본다.
 *
 * 미인증 안내는 켜진 기능만 말한다 — 게이트가 꺼져 있으면 무료 대화·미션은 인증 없이도 되므로 "받으려면 인증이
 * 필요하다"가 거짓이고, 정산이 꺼져 있으면 신청할 곳이 없다. 출석 보상은 게이트와 무관하게 늘 인증이 필요해 켜져
 * 있으면 언제나 말한다. */
export type IdentitySection = { kind: "hidden" } | { kind: "verified" } | { kind: "unverified"; message: string };

/** 인증을 요구하는 기능 중 켜진 것. */
export type IdentityFeatures = {
  payments: boolean;
  creatorPayout: boolean;
  /** 공개 가격 응답의 출석판 스위치(`attendance.enabled`). 비워 두면 꺼진 것으로 본다. */
  attendance?: boolean;
};

export function getIdentitySection(
  me: Pick<MeResponse, "identityVerified" | "identityGateEnabled">,
  features: IdentityFeatures,
): IdentitySection {
  if (!features.payments && !me.identityGateEnabled && !features.creatorPayout && !features.attendance) {
    return { kind: "hidden" };
  }
  if (me.identityVerified) return { kind: "verified" };
  return { kind: "unverified", message: unverifiedMessage(me.identityGateEnabled, features) };
}

/** 첫 문장은 켜진 기능을 "~하거나 ~하려면"으로 잇고, 둘째 문장은 나이 제한이 걸린 기능(구매·정산 신청)이 켜졌을 때만
 * 그 기능만 들어 말한다. 무료 대화·미션·출석은 나이 제한이 없어 둘째 문장에 넣지 않는다.
 *
 * 받는 조각은 출석판과 게이트의 조합으로 갈린다. 출석판이 켜지면 서버가 하루 무료 대화를 없애므로 무료 대화 대신 출석
 * 클로버를 말하고, 게이트가 꺼져 있으면 미션은 인증 없이 받으므로 미션을 말하지 않는다.
 *
 * 문장 조각은 어간과 끝 이음을 따로 둔다 — 받침에 따라 끝 이음이 갈린다("구매하려면" / "받으려면"). 가운데 이음 "거나"는
 * 받침과 무관하다. */
function unverifiedMessage(identityGateEnabled: boolean, features: IdentityFeatures): string {
  const receive = receiveStem(identityGateEnabled, features.attendance ?? false);
  const purposes = [
    features.payments && { stem: "클로버를 구매하", ending: "려면" },
    receive !== null && { stem: receive, ending: "으려면" },
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

/** 인증하면 받는 것의 어간. 아무것도 받지 않으면 null 이다(게이트도 출석판도 꺼짐). */
function receiveStem(identityGateEnabled: boolean, attendanceEnabled: boolean): string | null {
  if (attendanceEnabled) return identityGateEnabled ? "매일 출석 클로버와 미션 클로버를 받" : "매일 출석 클로버를 받";
  return identityGateEnabled ? "매일 무료 대화와 미션 클로버를 받" : null;
}
