import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@ai-character-chat/ui/components/chart";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { useTrendQuery, type AdminDashboardTrendPoint } from "../api/useTrendQuery";

type TrendMetricKey = "signups" | "contents" | "messages";

/** 세 지표 모두 `primary` 단색이다(One-Accent Rule — 이 시스템에 다인 시리즈용 카테고리
 * 팔레트가 없다). 자릿수가 서로 달라(가입 0~5 / 작품 0~40 / 메시지 0~800) 한 Y축에 겹치면
 * 두 개가 바닥에 눌리므로 차트 자체를 셋으로 나눴다 — 색이 아니라 차트 분리로 구분한다. */
const MINI_CHARTS: { key: TrendMetricKey; title: string; config: ChartConfig }[] = [
  { key: "signups", title: "신규 가입", config: { signups: { label: "신규 가입", color: "var(--primary)" } } },
  { key: "contents", title: "신규 작품", config: { contents: { label: "신규 작품", color: "var(--primary)" } } },
  { key: "messages", title: "메시지", config: { messages: { label: "메시지", color: "var(--primary)" } } },
];

function formatTickDate(date: string) {
  const [, month, day] = date.split("-");
  return `${month}/${day}`;
}

function MiniTrendChart({
  title,
  dataKey,
  data,
  config,
}: {
  title: string;
  dataKey: TrendMetricKey;
  data: AdminDashboardTrendPoint[];
  config: ChartConfig;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <h3 className="mb-4 text-sm font-medium text-foreground">{title}</h3>
      <ChartContainer config={config} className="aspect-auto h-48 w-full">
        <LineChart data={data} margin={{ left: 8, right: 8 }}>
          <CartesianGrid vertical={false} />
          <XAxis
            dataKey="date"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            tickFormatter={formatTickDate}
          />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} tickMargin={8} width={32} />
          <ChartTooltip
            content={<ChartTooltipContent labelFormatter={(label) => formatTickDate(String(label))} />}
          />
          <Line
            dataKey={dataKey}
            type="monotone"
            stroke={`var(--color-${dataKey})`}
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ChartContainer>
    </div>
  );
}

/** 최근 30일 추이를 신규 가입/신규 작품/메시지 세 차트로 나눠 보여준다. 세 차트가
 * `useTrendQuery` 하나를 공유하므로(요청 1개) 로딩·에러도 이 블록 전체 단위로 한 번만
 * 렌더한다 — counts/popular/activity 세 영역과는 여전히 독립이다(T-4). 데이터 없는 날은
 * API가 이미 0으로 채워서 준다. */
export function TrendChart() {
  const trendQuery = useTrendQuery();

  return (
    <div>
      <h2 className="mb-4 text-sm font-medium text-foreground">최근 30일 추이</h2>

      {trendQuery.isPending && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {MINI_CHARTS.map(({ key }) => (
            <div key={key} className="h-56 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      )}

      {trendQuery.isError && (
        <p className="text-sm text-destructive-text">
          추이 데이터를 불러오지 못했어요. 잠시 후 다시 시도해주세요.
        </p>
      )}

      {trendQuery.data && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {MINI_CHARTS.map(({ key, title, config }) => (
            <MiniTrendChart key={key} title={title} dataKey={key} data={trendQuery.data} config={config} />
          ))}
        </div>
      )}
    </div>
  );
}
