import { memo, useCallback } from "react";
import { Line, LineChart, XAxis, YAxis, type DotItemDotProps } from "recharts";

import type { ChartLine, ChartRow } from "../model/timelineChart";

type StatChartProps = {
  rows: ChartRow[];
  lines: ReadonlyArray<ChartLine>;
  domain: readonly [number, number];
  isolated: ReadonlySet<string>;
  count: number;
};

/** 선 끝·위아래가 잘리지 않게 두는 안쪽 여백(px). 겹쳐 그리는 점·눈금선 층도 같은 값으로 세로 자리를 잡는다(`inset-y-1`). */
const CHART_MARGIN = { top: 4, right: 0, bottom: 4, left: 0 } as const;
// `responsive` 차트는 크기를 style 의 CSS 크기로 읽는다 — 자리는 부모(높이 고정)가 정한다.
const CHART_SIZE = { width: "100%", height: "100%" } as const;
const ISOLATED_DOT_RADIUS = 2.5;

/**
 * 스탯 선만 그리는 차트. 축·눈금·툴팁·고른 턴은 겹쳐 그리는 층이 맡아, 턴을 옮기거나 마우스를 움직여도 이 차트는 다시 그리지
 * 않는다(받는 값이 그대로면 메모가 막는다). 가로 범위를 칸 순번 −0.5 ~ n−0.5 로 두고 좌우 여백을 0 으로 해, 칸 k 의 가운데가 폭의
 * (k + 0.5) / n 자리다 — 표지 줄·눈금 줄이 같은 비율로 놓여 세로로 맞는다. 선은 2px·둥근 이음이고, 앞뒤 칸과 이어지지 않는 점만 작게
 * 찍는다(선분이 없어 사라지지 않게). 등장 애니메이션은 없다.
 */
export const StatChart = memo(function StatChart({ rows, lines, domain, isolated, count }: StatChartProps) {
  const renderDot = useCallback(
    (props: DotItemDotProps) => {
      const { cx, cy, index, dataKey, stroke } = props;
      if (cx === undefined || cy === undefined || !isolated.has(`${String(dataKey)}:${index}`)) return null;
      return <circle cx={cx} cy={cy} r={ISOLATED_DOT_RADIUS} fill={stroke} />;
    },
    [isolated],
  );

  return (
    <LineChart responsive data={rows} margin={CHART_MARGIN} style={CHART_SIZE} accessibilityLayer={false}>
      <XAxis type="number" dataKey="index" domain={[-0.5, count - 0.5]} hide />
      <YAxis type="number" domain={[domain[0], domain[1]]} hide />
      {lines.flatMap((line) =>
        line.keys.map((key) => (
          <Line
            key={key}
            dataKey={key}
            type="linear"
            // 선 색은 테마 토큰이다 — 다크·라이트가 `light-dark()` 로 갈린다.
            stroke={`var(--color-${line.tone})`}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            dot={renderDot}
            activeDot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
        )),
      )}
    </LineChart>
  );
});
