import { describe, expect, it } from "vitest";

import type { AttendanceBoard } from "@/entities/clover";

import {
  formatClaimAreaLines,
  formatClaimButtonLabel,
  formatGuestTotal,
  formatNextSpecialSentence,
  formatProgress,
  RETURNING_SENTENCE,
} from "./attendanceCopy";
import type { ClaimArea } from "./attendanceView";

const SPECIAL_AMOUNTS: Record<number, number> = { 7: 1600, 14: 2400, 21: 3200, 28: 4800 };

function cellStatus(seq: number, claimed: number, canClaimToday: boolean): AttendanceBoard["cells"][number]["status"] {
  if (seq <= claimed) return "claimed";
  if (seq === claimed + 1 && canClaimToday) return "today";
  return "upcoming";
}
const REWARDS = Array.from({ length: 28 }, (_, index) => SPECIAL_AMOUNTS[index + 1] ?? 800);

function cellsWithClaimed(claimed: number, canClaimToday: boolean): AttendanceBoard["cells"] {
  return REWARDS.map((amount, index) => {
    const seq = index + 1;
    const status = cellStatus(seq, claimed, canClaimToday);
    return { seq, amount, status } as const;
  });
}

describe("formatClaimButtonLabel", () => {
  it("칸 번호와 천 단위 쉼표를 넣은 금액으로 말한다", () => {
    expect(formatClaimButtonLabel(7, 1600)).toBe("7일차 · 1,600클로버 받기");
  });
});

describe("formatProgress", () => {
  it("받은 칸 수를 28칸 중으로 말한다", () => {
    expect(formatProgress(6)).toBe("6 / 28일 출석 완료");
  });
});

describe("formatNextSpecialSentence", () => {
  // 날짜로 말하면 매일 온다는 전제를 깔아 "연속" 으로 읽힌다 — 남은 출석 수(칸 번호 차이)로 말한다.
  it("남은 출석 수는 남은 날 수가 아니라 칸 번호 차이다", () => {
    const sentence = formatNextSpecialSentence({
      cells: cellsWithClaimed(3, true),
      canClaimToday: true,
      nextSpecial: { seq: 7, amount: 1600, daysUntil: 99 },
    });
    expect(sentence).toBe("다음 특별 보상까지 출석 4번");
  });

  it("오늘 받을 칸이 특별 보상이면 그렇게 말한다", () => {
    expect(
      formatNextSpecialSentence({
        cells: cellsWithClaimed(6, true),
        canClaimToday: true,
        nextSpecial: { seq: 7, amount: 1600, daysUntil: 0 },
      }),
    ).toBe("오늘 받으면 특별 보상이에요");
  });

  it("오늘 이미 받았으면 다음 출석 한 번이 특별 보상이어도 오늘을 말하지 않는다", () => {
    expect(
      formatNextSpecialSentence({
        cells: cellsWithClaimed(6, false),
        canClaimToday: false,
        nextSpecial: { seq: 7, amount: 1600, daysUntil: 1 },
      }),
    ).toBe("다음 특별 보상까지 출석 1번");
  });

  it("남은 특별 보상이 없으면 문장이 없다", () => {
    expect(
      formatNextSpecialSentence({ cells: cellsWithClaimed(28, false), canClaimToday: false, nextSpecial: null }),
    ).toBeNull();
  });
});

describe("formatGuestTotal", () => {
  // 합은 받은 보상표에서 계산한다 — 보상표가 바뀌어도 화면에 적힌 숫자가 따라간다.
  it("보상표의 합을 천 단위 쉼표로 말한다", () => {
    expect(formatGuestTotal(REWARDS)).toBe("28일 동안 모두 받으면 31,200클로버");
    expect(formatGuestTotal([100, 200])).toBe("28일 동안 모두 받으면 300클로버");
  });
});

describe("formatClaimAreaLines", () => {
  it("확인 중 문장", () => {
    expect(formatClaimAreaLines({ kind: "checking" })).toEqual(["지급 결과를 확인하고 있어요."]);
  });

  it("확정 실패 문장", () => {
    expect(formatClaimAreaLines({ kind: "failed" })).toEqual(["보상을 받지 못했어요. 다시 시도해 주세요."]);
  });

  it("잠시 멈춤 문장", () => {
    expect(formatClaimAreaLines({ kind: "paused" })).toEqual([
      "지금은 출석 보상을 잠시 받을 수 없어요. 잠시 뒤 다시 시도해 주세요.",
    ]);
  });

  it("완주 문장", () => {
    expect(formatClaimAreaLines({ kind: "completed" })).toEqual(["28일 출석 완주! 내일부터 새로운 출석판이 시작돼요."]);
  });

  it("오늘 받음은 받은 금액과 다음 보상 시각을 말한다", () => {
    expect(formatClaimAreaLines({ kind: "claimed", amount: 1600 })).toEqual([
      "오늘 출석 완료! 1,600클로버를 받았어요.",
      "다음 보상은 내일 00:00부터 받을 수 있어요.",
    ]);
  });

  // 이유를 말하면 오늘 탈퇴한 사실이 드러난다.
  it("오늘 불가는 이유를 말하지 않는다", () => {
    expect(formatClaimAreaLines({ kind: "unavailable" })).toEqual(["오늘은 받을 수 없어요. 내일 다시 와 주세요."]);
  });

  it("인증 안내 자리는 인증 안내가 문장을 맡아 여기서는 비어 있다", () => {
    expect(formatClaimAreaLines({ kind: "identity" })).toEqual([]);
  });
});

describe("복귀 문장", () => {
  it("지난 출석에 이어서 받는다고 말한다", () => {
    expect(RETURNING_SENTENCE).toBe("돌아오셨네요! 지난 출석에 이어서 받을 수 있어요.");
  });
});

// 출석은 하루 쉬어도 이어지는 누적 진도다 — "연속" 은 빠지면 끊긴다는 약속으로 읽힌다.
describe("출석 문구 금지어", () => {
  const AREAS: Exclude<ClaimArea, { kind: "claim" }>[] = [
    { kind: "checking" },
    { kind: "failed" },
    { kind: "paused" },
    { kind: "identity" },
    { kind: "completed" },
    { kind: "claimed", amount: 4800 },
    { kind: "unavailable" },
  ];

  it("어떤 상태 문구에도 '연속' 이 없다", () => {
    const texts = [
      ...AREAS.flatMap((area) => formatClaimAreaLines(area)),
      formatClaimButtonLabel(28, 4800),
      formatProgress(27),
      formatGuestTotal(REWARDS),
      formatNextSpecialSentence({ cells: cellsWithClaimed(6, true), canClaimToday: true, nextSpecial: { seq: 7, amount: 1600, daysUntil: 0 } }),
      formatNextSpecialSentence({ cells: cellsWithClaimed(3, true), canClaimToday: true, nextSpecial: { seq: 7, amount: 1600, daysUntil: 3 } }),
      RETURNING_SENTENCE,
    ];
    for (const text of texts) expect(text).not.toContain("연속");
    expect(RETURNING_SENTENCE).not.toBe("");
  });
});
