import { describe, expect, it } from "vitest";

import { projectCloverMissionState } from "./cloverMissionState";

describe("projectCloverMissionState", () => {
  it("미달성이면 unachieved다 — 받기 버튼이 없어야 한다", () => {
    expect(projectCloverMissionState({ achieved: false, claimed: false })).toBe("unachieved");
  });

  it("달성했고 아직 청구 전이면 claimable이다 — 이때만 '받기' 버튼을 보여준다", () => {
    expect(projectCloverMissionState({ achieved: true, claimed: false })).toBe("claimable");
  });

  it("달성하고 청구까지 마쳤으면 claimed다", () => {
    expect(projectCloverMissionState({ achieved: true, claimed: true })).toBe("claimed");
  });

  it("청구 이후 달성 신호가 사라져도(예: first_message 청구 뒤 메시지 전부 삭제) claimed를 유지한다 — claimed가 achieved보다 우선한다. achieved===false로만 판정하면 이 케이스에서 도로 unachieved로 잘못 떨어진다", () => {
    expect(projectCloverMissionState({ achieved: false, claimed: true })).toBe("claimed");
  });
});
