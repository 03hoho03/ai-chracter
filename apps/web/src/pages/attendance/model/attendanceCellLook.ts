import type { AttendanceCell } from "@/entities/clover";

import { formatCloverAmount } from "./attendanceCopy";

export type AttendanceCellLook = {
  cellClassName: string;
  amountClassName: string;
  statusClassName: string;
  showGift: boolean;
};

/** 금액이 큰 칸. 보상표 금액이 아니라 칸 자리로 정한다 — 화면은 특별일이 7일마다라는 사실만 안다. */
const SPECIAL_EVERY = 7;

/** 상태마다 표면·잉크. 색은 primary 와 무채 명도 사다리만 쓴다. 상태는 색 + 글자(또는 아이콘) + 모양(테두리 두께·채움
 * 유무) 셋으로 갈려 흑백에서도 구분된다.
 *
 * - 받음: 채움 없이 배경 위 테두리 한 줄 — 판에서 물러난 칸. 라이트의 `secondary` 채움 위 `muted-foreground` 는 12px 에
 *   대비가 모자라 채움을 뺐다.
 * - 오늘: primary 는 테두리·잉크로만 쓴다. 이 화면의 솔리드 채움은 유일한 행동인 수령 버튼 하나다.
 * - 예정: 카드 표면. 특별일 예정은 사다리 한 칸 위 표면과 굵은 금액으로 띄운다. 받았거나 오늘인 특별일은 그 상태의
 *   모양을 따르고 선물 표시만 남는다. */
const LOOKS = {
  claimed: {
    cellClassName: "border border-border bg-background",
    amountClassName: "text-muted-foreground",
    statusClassName: "text-muted-foreground",
  },
  today: {
    cellClassName: "border-2 border-primary bg-card",
    amountClassName: "font-semibold text-foreground",
    statusClassName: "font-semibold text-primary",
  },
  upcoming: {
    cellClassName: "bg-card",
    amountClassName: "text-foreground",
    statusClassName: "text-muted-foreground",
  },
  specialUpcoming: {
    cellClassName: "bg-secondary",
    amountClassName: "font-bold text-foreground",
    statusClassName: "text-muted-foreground",
  },
} as const;

export function attendanceCellLook(cell: Pick<AttendanceCell, "seq" | "status">): AttendanceCellLook {
  const isSpecial = cell.seq % SPECIAL_EVERY === 0;
  const look = cell.status === "upcoming" && isSpecial ? LOOKS.specialUpcoming : LOOKS[cell.status];
  return { ...look, showGift: isSpecial };
}

/** `compact` 는 `sm` 미만 칸이다. 320px 폭의 7열 칸에서는 쉼표까지 넣은 "4,800" 이 가장 좁은 오늘 칸(테두리 2px)의 안쪽
 * 폭을 넘는다. 한 칸만 빼면 칸끼리 표기가 갈려 좁은 칸은 전부 뺀다. 낭독 문장과 버튼·진도 문구는 쉼표를 그대로 쓴다. */
export function formatCellAmount(amount: number, compact: boolean): string {
  return compact ? String(amount) : formatCloverAmount(amount);
}

/** 칸의 상태 글자. 글자 없이 아이콘만 둘 때는 null — 좁은 받음 칸은 "받음" 과 체크 아이콘을 함께 두면 안쪽 폭을 넘어
 * 아이콘만 두고, 낭독 문장이 "받음" 을 말한다. */
export function cellStatusLabel(status: AttendanceCell["status"], compact: boolean): string | null {
  switch (status) {
    case "claimed":
      return compact ? null : "받음";
    case "today":
      return "오늘";
    case "upcoming":
      return "예정";
  }
}
