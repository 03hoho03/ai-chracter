import { describe, expect, it } from "vitest";

import type { AutosaveStatus } from "./autosaveStatus";
import { saveStatusView } from "./saveStatusText";

// 로컬 시각으로 만든다 — 글자는 보는 사람의 시계로 읽는다.
const AT_23_42 = new Date(2026, 9, 27, 23, 42).getTime();
const AT_09_05 = new Date(2026, 9, 27, 9, 5).getTime();

describe("saveStatusView", () => {
  // 아직 저장한 적 없는 화면은 상태가 아니라 저장 계약을 말한다 — 작가가 "자동저장"을 처음 만나는 자리가 실패 토스트가 되지 않게.
  it("idle 은 자동저장 안내문이다", () => {
    expect(saveStatusView("idle", true, undefined)).toEqual({
      text: "변경사항은 자동으로 저장돼요.",
      offersCopy: false,
      isFailure: false,
    });
  });

  it.each<[AutosaveStatus, string]>([
    ["pending", "저장 대기 중"],
    ["saving", "저장 중"],
    ["failed", "저장 실패"],
  ])("%s → %s", (status, text) => {
    expect(saveStatusView(status, true, AT_23_42).text).toBe(text);
  });

  it("저장됨에는 마지막으로 성공한 저장의 시각이 붙는다", () => {
    expect(saveStatusView("saved", true, AT_23_42).text).toBe("저장됨 · 오후 11:42");
    expect(saveStatusView("saved", true, AT_09_05).text).toBe("저장됨 · 오전 9:05");
  });

  // 시각을 손으로 조립하므로 0시·12시가 "0:00"이 되거나 오전·오후가 뒤바뀌지 않는지 본다.
  it("자정은 오전 12시, 정오는 오후 12시다", () => {
    expect(saveStatusView("saved", true, new Date(2026, 9, 27, 0, 0).getTime()).text).toBe("저장됨 · 오전 12:00");
    expect(saveStatusView("saved", true, new Date(2026, 9, 27, 12, 0).getTime()).text).toBe("저장됨 · 오후 12:00");
  });

  it("실패에서만 실패 표시와 내용 복사를 낸다", () => {
    expect(saveStatusView("failed", true, AT_23_42)).toEqual({ text: "저장 실패", offersCopy: true, isFailure: true });
    for (const status of ["idle", "pending", "saving", "saved"] as const) {
      const view = saveStatusView(status, true, AT_23_42);
      expect(view.offersCopy).toBe(false);
      expect(view.isFailure).toBe(false);
    }
  });

  // 오프라인이면 저장 요청이 멈춰 저장 상태가 "저장 중"에 남는다 — 연결 상태를 먼저 보지 않으면 끝없는 "저장 중"이 뜬다.
  // 연결이 길게 끊기면 편집이 이 탭 메모리에만 있으므로 복사를 낸다.
  it.each<AutosaveStatus>(["idle", "pending", "saving", "saved", "failed"])("오프라인이면 %s 이어도 연결 끊김이다", (status) => {
    expect(saveStatusView(status, false, AT_23_42)).toEqual({
      text: "연결 끊김 · 연결되면 저장돼요",
      offersCopy: true,
      isFailure: false,
    });
  });
});
