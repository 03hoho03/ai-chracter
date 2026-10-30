import { assertNever } from "@/shared/lib/assertNever";
import { formatUsd } from "@/shared/lib/formatNumber";

import { lowerBoundNote, type CostView } from "../model/runFormat";

/**
 * 원가 한 칸. `$0.0000` 과 "원가를 모름"이 같은 모양이 되지 않게 갈래마다 다르게 적는다 — 턴 기록이 없으면 "내보내기 필요",
 * 합에서 빠진 것이 있으면 `≥` 를 붙인 하한과 그 까닭.
 */
type CostTextProps = {
  cost: CostView;
  /** 하한일 때 빠진 것을 글로도 적는다(미리보기). 표에서는 칸이 좁아 마우스를 올려야 보인다. */
  hasNote?: boolean;
};

export function CostText({ cost, hasNote = false }: CostTextProps) {
  switch (cost.kind) {
    case "none":
      return null;
    case "needsExport":
      return <span className="text-ink-muted">내보내기 필요</span>;
    case "exact":
      return <data value={cost.usd}>{formatUsd(cost.usd)}</data>;
    case "lowerBound":
      return (
        <>
          <data value={cost.usd} title={lowerBoundNote(cost)}>
            <span className="text-ink-muted">≥ </span>
            {formatUsd(cost.usd)}
          </data>
          {hasNote && <span className="block text-label text-ink-muted">{lowerBoundNote(cost)}</span>}
        </>
      );
    default:
      return assertNever(cost);
  }
}
