import { describe, expect, it } from "vitest";

import {
  consentedVersionsFor,
  hasPendingReconsent,
  pendingConsentDocuments,
  pendingConsentUnits,
} from "./consentUnits";

const NONE = { termsReconsentRequired: false, collectionReconsentRequired: false, transferReconsentRequired: false };

describe("pendingConsentUnits", () => {
  it("켜진 플래그의 단위만 가입 화면 순서로 준다", () => {
    expect(
      pendingConsentUnits({ termsReconsentRequired: true, collectionReconsentRequired: false, transferReconsentRequired: true }),
    ).toEqual(["terms", "transfer"]);
  });

  // 국외이전만 다시 받는 판이면 수집·이용 체크를 요구하지 않는다.
  it("국외이전 하나만 걸리면 그 하나다", () => {
    expect(pendingConsentUnits({ ...NONE, transferReconsentRequired: true })).toEqual(["transfer"]);
  });

  it("아무것도 안 걸리면 비고, hasPendingReconsent 도 거짓이다", () => {
    expect(pendingConsentUnits(NONE)).toEqual([]);
    expect(hasPendingReconsent(NONE)).toBe(false);
    expect(hasPendingReconsent({ ...NONE, collectionReconsentRequired: true })).toBe(true);
  });
});

describe("pendingConsentDocuments", () => {
  it("처리방침의 두 단위는 문서 하나로 묶는다", () => {
    expect(pendingConsentDocuments(["collection", "transfer"])).toEqual(["privacy"]);
    expect(pendingConsentDocuments(["terms", "collection", "transfer"])).toEqual(["terms", "privacy"]);
    expect(pendingConsentDocuments(["terms"])).toEqual(["terms"]);
  });
});

describe("consentedVersionsFor", () => {
  const versions = { terms: "2026-10-12", collection: "2026-10-13", transfer: "2026-09-06" };

  it("그 문서에서 다시 동의할 단위의 판만 고른다", () => {
    expect(consentedVersionsFor("privacy", ["collection", "transfer"], versions)).toEqual(["2026-10-13", "2026-09-06"]);
    // 국외이전만 걸렸으면 수집·이용 판은 기준 후보가 아니다.
    expect(consentedVersionsFor("privacy", ["terms", "transfer"], versions)).toEqual(["2026-09-06"]);
    expect(consentedVersionsFor("terms", ["terms", "transfer"], versions)).toEqual(["2026-10-12"]);
  });
});
