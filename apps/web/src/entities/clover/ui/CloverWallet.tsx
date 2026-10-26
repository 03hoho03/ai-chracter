import type { CloverBalanceResponse } from "../api/cloverBalanceQueryOptions";
import { CloverIcon } from "./CloverIcon";

type CloverWalletProps = {
  balance: number;
  /** 잔액을 나눈 유료·보너스·무료 몫. 이 칸이 없는 옛 API 응답(web 과 API 가 따로 배포되는 구간)이면 비어 온다 —
   * 그때는 총잔액만 그린다. */
  breakdown: CloverBalanceResponse["breakdown"] | undefined;
};

const BREAKDOWN_ROWS = [
  { key: "paid", label: "유료" },
  { key: "bonus", label: "보너스" },
  { key: "free", label: "무료" },
] as const satisfies readonly { key: keyof CloverBalanceResponse["breakdown"]; label: string }[];

/** 내 클로버 — 총잔액과 그 구성. 클로버 충전 화면에서 쓴다(채팅 입력 바 등 한 줄 잔량은 `CloverBalance`).
 *
 * 세 몫은 유료 → 보너스 → 무료 순서다. 이 줄을 보는 이유는 대개 "환불할 수 있는 몫이 얼마 남았나"라 환불 대상인 유료가
 * 먼저다. 쓰이는 순서(무료 → 보너스 → 유료)는 같은 화면의 안내가 말한다. 숫자는 축약 없이 전체를 보이고 그대로 읽힌다.
 * 총잔액은 섹션 제목 단(`text-xl`)이다 — `text-2xl` 은 페이지 제목 몫이다. 초록은 아이콘 그림에만 있다. */
export function CloverWallet({ balance, breakdown }: CloverWalletProps) {
  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-center gap-1.5 text-xl font-semibold tabular-nums text-foreground">
        <CloverIcon className="size-5" />
        클로버 {balance.toLocaleString()}개
      </p>
      {breakdown && (
        <dl className="flex flex-col gap-1.5 text-sm">
          {BREAKDOWN_ROWS.map((row) => (
            <div key={row.key} className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="tabular-nums text-foreground">{breakdown[row.key].toLocaleString()}개</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
