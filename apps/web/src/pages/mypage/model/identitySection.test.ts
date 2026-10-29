import { describe, expect, it } from "vitest";

import { getIdentitySection } from "./identitySection";

type Combo = { payments: boolean; gate: boolean; creatorPayout: boolean };

function unverifiedMessage({ payments, gate, creatorPayout }: Combo): string {
  const section = getIdentitySection({ identityVerified: false, identityGateEnabled: gate }, { payments, creatorPayout });
  if (section.kind !== "unverified") throw new Error(`expected unverified, got ${section.kind}`);
  return section.message;
}

// 기능마다 그 기능이 켜졌을 때만 나와야 하는 낱말. 꺼진 기능을 인증 사유로 말하면 거짓이다.
const PURPOSE_WORDS = {
  payments: "구매",
  gate: "무료 대화",
  creatorPayout: "정산",
} as const satisfies Record<keyof Combo, string>;

const ENABLED_COMBOS: Combo[] = [
  { payments: true, gate: false, creatorPayout: false },
  { payments: false, gate: true, creatorPayout: false },
  { payments: false, gate: false, creatorPayout: true },
  { payments: true, gate: true, creatorPayout: false },
  { payments: true, gate: false, creatorPayout: true },
  { payments: false, gate: true, creatorPayout: true },
  { payments: true, gate: true, creatorPayout: true },
];

describe("getIdentitySection", () => {
  it("인증을 요구하는 기능이 하나도 켜져 있지 않으면 보이지 않는다", () => {
    expect(
      getIdentitySection({ identityVerified: false, identityGateEnabled: false }, { payments: false, creatorPayout: false }),
    ).toEqual({ kind: "hidden" });
  });

  // 어느 하나만 먼저 켜는 배포에서 다른 스위치만 보면 미인증 회원이 인증할 길이 없다.
  it.each(ENABLED_COMBOS)("%o 조합이면 보이고 켜진 기능만 말한다", (combo) => {
    const message = unverifiedMessage(combo);
    for (const key of ["payments", "gate", "creatorPayout"] as const) {
      if (combo[key]) expect(message).toContain(PURPOSE_WORDS[key]);
      else expect(message).not.toContain(PURPOSE_WORDS[key]);
    }
  });

  // 나이 제한은 구매와 정산 신청에만 있다 — 무료 대화만 켜졌을 때 나이를 말하면 받을 수 있는 회원이 물러난다.
  it.each(ENABLED_COMBOS)("%o 조합에서 나이 제한은 구매·정산이 켜졌을 때만 말한다", (combo) => {
    const message = unverifiedMessage(combo);
    if (combo.payments || combo.creatorPayout) expect(message).toContain("만 19세 이상");
    else expect(message).not.toContain("만 19세");
  });

  it("문장은 켜진 기능을 하나의 조건절로 잇는다", () => {
    expect(unverifiedMessage({ payments: false, gate: false, creatorPayout: true })).toBe(
      "크리에이터 정산을 신청하려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 신청할 수 있어요.",
    );
    expect(unverifiedMessage({ payments: false, gate: true, creatorPayout: false })).toBe(
      "매일 무료 대화와 미션 클로버를 받으려면 휴대폰 본인인증이 필요해요.",
    );
    expect(unverifiedMessage({ payments: true, gate: true, creatorPayout: true })).toBe(
      "클로버를 구매하거나 매일 무료 대화와 미션 클로버를 받거나 크리에이터 정산을 신청하려면 휴대폰 본인인증이 필요해요. 클로버 구매와 정산 신청은 만 19세 이상만 할 수 있어요.",
    );
  });

  it("인증을 마쳤으면 인증됨이다", () => {
    expect(
      getIdentitySection({ identityVerified: true, identityGateEnabled: false }, { payments: false, creatorPayout: true }),
    ).toEqual({ kind: "verified" });
  });
});

/** 출석 보상은 게이트 스위치와 무관하게 늘 본인인증이 필요하다. 미션은 게이트를 따른다 — 게이트가 꺼져 있으면 미인증도
 * 미션을 받으므로 그때는 미션을 인증 사유로 말하지 않는다. */
describe("getIdentitySection — 출석판", () => {
  function messageWith(gate: boolean, features: { payments: boolean; creatorPayout: boolean; attendance: boolean }): string {
    const section = getIdentitySection({ identityVerified: false, identityGateEnabled: gate }, features);
    if (section.kind !== "unverified") throw new Error(`expected unverified, got ${section.kind}`);
    return section.message;
  }

  it("출석만 켜져 있어도 보인다", () => {
    expect(
      getIdentitySection(
        { identityVerified: false, identityGateEnabled: false },
        { payments: false, creatorPayout: false, attendance: true },
      ).kind,
    ).toBe("unverified");
  });

  it("출석까지 전부 꺼져 있으면 보이지 않는다", () => {
    expect(
      getIdentitySection(
        { identityVerified: false, identityGateEnabled: false },
        { payments: false, creatorPayout: false, attendance: false },
      ),
    ).toEqual({ kind: "hidden" });
  });

  it("출석만 켜져 있고 인증을 마쳤으면 인증됨이다", () => {
    expect(
      getIdentitySection(
        { identityVerified: true, identityGateEnabled: false },
        { payments: false, creatorPayout: false, attendance: true },
      ),
    ).toEqual({ kind: "verified" });
  });

  it("출석과 게이트가 켜져 있으면 출석 클로버와 미션 클로버를 말한다", () => {
    expect(messageWith(true, { payments: false, creatorPayout: false, attendance: true })).toBe(
      "매일 출석 클로버와 미션 클로버를 받으려면 휴대폰 본인인증이 필요해요.",
    );
  });

  it("출석만 켜지고 게이트가 꺼져 있으면 미션을 말하지 않는다", () => {
    const message = messageWith(false, { payments: false, creatorPayout: false, attendance: true });
    expect(message).toBe("매일 출석 클로버를 받으려면 휴대폰 본인인증이 필요해요.");
    expect(message).not.toContain("미션");
  });

  it("출석이 꺼져 있고 게이트가 켜져 있으면 지금 문장 그대로다", () => {
    expect(messageWith(true, { payments: false, creatorPayout: false, attendance: false })).toBe(
      "매일 무료 대화와 미션 클로버를 받으려면 휴대폰 본인인증이 필요해요.",
    );
  });

  it("출석과 결제가 켜져 있으면 구매에 이어 출석을 말하고 나이 문장을 남긴다", () => {
    expect(messageWith(false, { payments: true, creatorPayout: false, attendance: true })).toBe(
      "클로버를 구매하거나 매일 출석 클로버를 받으려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.",
    );
    expect(messageWith(true, { payments: true, creatorPayout: false, attendance: true })).toBe(
      "클로버를 구매하거나 매일 출석 클로버와 미션 클로버를 받으려면 휴대폰 본인인증이 필요해요. 만 19세 이상만 구매할 수 있어요.",
    );
  });

  it("출석이 켜져 있으면 무료 대화를 말하지 않는다", () => {
    for (const gate of [false, true]) {
      expect(messageWith(gate, { payments: true, creatorPayout: true, attendance: true })).not.toContain("무료 대화");
    }
  });
});
