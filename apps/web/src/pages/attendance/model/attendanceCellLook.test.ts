import { describe, expect, it } from "vitest";

import { attendanceCellLook, cellStatusLabel, formatCellAmount } from "./attendanceCellLook";

/** 특별일이 아닌 칸의 세 상태와 특별일 예정 칸. */
function baseLooks() {
  return {
    claimed: attendanceCellLook({ seq: 3, status: "claimed" }),
    today: attendanceCellLook({ seq: 3, status: "today" }),
    upcoming: attendanceCellLook({ seq: 3, status: "upcoming" }),
    specialUpcoming: attendanceCellLook({ seq: 7, status: "upcoming" }),
  };
}

function classesOf(look: ReturnType<typeof attendanceCellLook>): string {
  return [look.cellClassName, look.amountClassName, look.statusClassName].join(" ");
}

describe("attendanceCellLook", () => {
  it("받음·오늘·예정·특별일 예정 네 모양이 서로 다르다", () => {
    const { claimed, today, upcoming, specialUpcoming } = baseLooks();
    const looks = [claimed, today, upcoming, specialUpcoming].map(classesOf);
    expect(new Set(looks).size).toBe(4);
  });

  // primary 는 테두리·잉크로만 쓴다. 솔리드 채움은 화면의 유일한 행동인 수령 버튼 하나다.
  it("오늘 칸만 primary 테두리를 갖는다", () => {
    const { claimed, today, upcoming, specialUpcoming } = baseLooks();
    expect(today.cellClassName).toContain("border-primary");
    for (const look of [claimed, upcoming, specialUpcoming]) expect(look.cellClassName).not.toContain("border-primary");
  });

  it("어떤 칸도 primary 로 채우지 않는다", () => {
    for (const status of ["claimed", "today", "upcoming"] as const) {
      for (const seq of [3, 7, 28]) expect(classesOf(attendanceCellLook({ seq, status }))).not.toContain("bg-primary");
    }
  });

  it("특별일은 7·14·21·28칸이고 선물 표시를 단다", () => {
    for (const seq of [7, 14, 21, 28]) expect(attendanceCellLook({ seq, status: "upcoming" }).showGift).toBe(true);
    for (const seq of [1, 6, 8, 27]) expect(attendanceCellLook({ seq, status: "upcoming" }).showGift).toBe(false);
  });

  // 오늘·받음이면 그 상태의 모양을 따르고 선물 표시만 남는다.
  it("받았거나 오늘인 특별일은 그 상태의 모양에 선물 표시만 더한다", () => {
    const { claimed, today } = baseLooks();
    const specialClaimed = attendanceCellLook({ seq: 7, status: "claimed" });
    const specialToday = attendanceCellLook({ seq: 7, status: "today" });
    expect(classesOf(specialClaimed)).toBe(classesOf(claimed));
    expect(classesOf(specialToday)).toBe(classesOf(today));
    expect(specialClaimed.showGift).toBe(true);
    expect(specialToday.showGift).toBe(true);
  });
});

describe("formatCellAmount", () => {
  // 320px 폭의 7열 칸에서 쉼표까지 넣은 "4,800" 은 오늘 칸 안쪽 폭을 넘는다. 한 칸만 빼면 칸끼리 표기가 갈려 전부 뺀다.
  it("좁은 칸은 쉼표 없이 쓴다", () => {
    expect(formatCellAmount(4800, true)).toBe("4800");
    expect(formatCellAmount(800, true)).toBe("800");
  });

  it("넓은 칸은 천 단위 쉼표를 쓴다", () => {
    expect(formatCellAmount(4800, false)).toBe("4,800");
  });
});

describe("cellStatusLabel", () => {
  // "받음" 글자와 아이콘을 함께 두면 좁은 칸의 안쪽 폭을 넘는다 — 낭독 문장이 "받음" 을 말한다.
  it("좁은 받음 칸은 글자 없이 아이콘만 둔다", () => {
    expect(cellStatusLabel("claimed", true)).toBeNull();
  });

  it("넓은 받음 칸은 글자를 쓴다", () => {
    expect(cellStatusLabel("claimed", false)).toBe("받음");
  });

  it.each([true, false])("오늘·예정은 칸 폭과 무관하게 글자를 쓴다(좁은 칸 %s)", (compact) => {
    expect(cellStatusLabel("today", compact)).toBe("오늘");
    expect(cellStatusLabel("upcoming", compact)).toBe("예정");
  });
});
