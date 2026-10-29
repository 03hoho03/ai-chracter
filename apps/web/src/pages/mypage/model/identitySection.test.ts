import { describe, expect, it } from "vitest";

import { getIdentitySection } from "./identitySection";

type Combo = { payments: boolean; gate: boolean; creatorPayout: boolean };

function unverifiedMessage({ payments, gate, creatorPayout }: Combo): string {
  const section = getIdentitySection({ identityVerified: false, identityGateEnabled: gate }, { payments, creatorPayout });
  if (section.kind !== "unverified") throw new Error(`expected unverified, got ${section.kind}`);
  return section.message;
}

// 기능마다 그 기능이 켜졌을 때만 나와야 하는 낱말. 꺼진 기능을 인증 사유로 말하면 거짓이다. 게이트가 꺼져 있으면 미인증도
// 미션을 받으므로 미션은 게이트가 켜졌을 때만 인증 사유다.
const PURPOSE_WORDS = {
  payments: "구매",
  gate: "미션",
  creatorPayout: "정산",
} as const satisfies Record<keyof Combo, string>;

const ALL_COMBOS: Combo[] = [
  { payments: false, gate: false, creatorPayout: false },
  { payments: true, gate: false, creatorPayout: false },
  { payments: false, gate: true, creatorPayout: false },
  { payments: false, gate: false, creatorPayout: true },
  { payments: true, gate: true, creatorPayout: false },
  { payments: true, gate: false, creatorPayout: true },
  { payments: false, gate: true, creatorPayout: true },
  { payments: true, gate: true, creatorPayout: true },
];

/** 출석 보상은 게이트 스위치와 무관하게 늘 본인인증이 필요하고 출석판은 늘 열려 있다. 그래서 출석판 스위치를 읽지 않고도
 * 이 자리는 늘 보이고, 미인증 안내는 언제나 출석 클로버를 말한다. 하루 무료 대화는 없어 말하지 않는다. */
describe("getIdentitySection", () => {
  it("결제·게이트·정산이 모두 꺼져 있어도 출석 보상 때문에 보인다", () => {
    expect(
      getIdentitySection({ identityVerified: false, identityGateEnabled: false }, { payments: false, creatorPayout: false })
        .kind,
    ).toBe("unverified");
  });

  it.each(ALL_COMBOS)("%o 조합이면 켜진 기능과 출석 클로버를 말한다", (combo) => {
    const message = unverifiedMessage(combo);
    expect(message).toContain("매일 출석 클로버");
    for (const key of ["payments", "gate", "creatorPayout"] as const) {
      if (combo[key]) expect(message).toContain(PURPOSE_WORDS[key]);
      else expect(message).not.toContain(PURPOSE_WORDS[key]);
    }
  });

  it.each(ALL_COMBOS)("%o 조합에서 무료 대화를 말하지 않는다", (combo) => {
    expect(unverifiedMessage(combo)).not.toContain("무료 대화");
  });

  // 나이 제한은 구매와 정산 신청에만 있다 — 출석·미션만 말할 때 나이를 말하면 받을 수 있는 회원이 물러난다.
  it.each(ALL_COMBOS)("%o 조합에서 나이 제한은 구매·정산이 켜졌을 때만 말한다", (combo) => {
    const message = unverifiedMessage(combo);
    if (combo.payments || combo.creatorPayout) expect(message).toContain("만 19세 이상");
    else expect(message).not.toContain("만 19세");
  });

  it("문장은 켜진 기능을 하나의 조건절로 잇는다", () => {
    expect(unverifiedMessage({ payments: false, gate: false, creatorPayout: false })).toBe(
      "매일 출석 클로버를 받으려면 휴대폰 본인인증이 필요해요.",
    );
    expect(unverifiedMessage({ payments: false, gate: true, creatorPayout: false })).toBe(
      "매일 출석 클로버와 미션 클로버를 받으려면 휴대폰 본인인증이 필요해요.",
    );
    expect(unverifiedMessage({ payments: false, gate: false, creatorPayout: true })).toBe(
      "매일 출석 클로버를 받거나 크리에이터 정산을 신청하려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 신청할 수 있어요.",
    );
    expect(unverifiedMessage({ payments: true, gate: false, creatorPayout: false })).toBe(
      "클로버를 구매하거나 매일 출석 클로버를 받으려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.",
    );
    expect(unverifiedMessage({ payments: true, gate: true, creatorPayout: false })).toBe(
      "클로버를 구매하거나 매일 출석 클로버와 미션 클로버를 받으려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.",
    );
    expect(unverifiedMessage({ payments: true, gate: true, creatorPayout: true })).toBe(
      "클로버를 구매하거나 매일 출석 클로버와 미션 클로버를 받거나 크리에이터 정산을 신청하려면 휴대폰 본인인증이 필요해요. 클로버 구매와 정산 신청은 만 19세 이상만 할 수 있어요.",
    );
  });

  it.each([false, true])("인증을 마쳤으면 인증됨이다(게이트 %s)", (gate) => {
    expect(
      getIdentitySection({ identityVerified: true, identityGateEnabled: gate }, { payments: false, creatorPayout: false }),
    ).toEqual({ kind: "verified" });
  });
});
