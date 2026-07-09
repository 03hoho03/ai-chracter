import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@ai-character-chat/ui/components/chart";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { useUsageMetricsQuery } from "../../../entities/usage-metrics";

const chartConfig = {
  messageCount: {
    label: "메시지 전송량",
    color: "var(--primary)",
  },
} satisfies ChartConfig;

function formatAverage(value: number) {
  return value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
}

function formatTickDate(date: string) {
  const [, month, day] = date.split("-");
  return `${month}/${day}`;
}

interface UsageMetricsPageProps {
  from: string;
  to: string;
  onRangeChange: (range: Partial<{ from: string; to: string }>) => void;
}

export function UsageMetricsPage({ from, to, onRangeChange }: UsageMetricsPageProps) {
  const usageMetricsQuery = useUsageMetricsQuery({ from, to });

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 px-6 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">사용량 모니터링</h1>

        <div className="flex items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="usage-from" className="text-xs text-muted-foreground">
              시작일
            </Label>
            <Input
              id="usage-from"
              type="date"
              value={from}
              max={to}
              onChange={(event) => onRangeChange({ from: event.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="usage-to" className="text-xs text-muted-foreground">
              종료일
            </Label>
            <Input
              id="usage-to"
              type="date"
              value={to}
              min={from}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(event) => onRangeChange({ to: event.target.value })}
            />
          </div>
        </div>
      </div>

      {usageMetricsQuery.isPending && (
        <div className="h-64 animate-pulse rounded-xl bg-muted" />
      )}

      {usageMetricsQuery.isError && (
        <p className="text-sm text-destructive">
          사용량 지표를 불러오지 못했어요. 기간을 확인한 뒤 다시 시도해주세요.
        </p>
      )}

      {usageMetricsQuery.data && (
        <>
          <div className="flex gap-4">
            <div className="flex flex-1 flex-col gap-2 rounded-xl border border-border bg-card p-6">
              <span className="text-sm text-muted-foreground">사용자 1인당 일일 평균 메시지 전송 수</span>
              <span className="text-3xl font-bold tabular-nums text-foreground">
                {formatAverage(usageMetricsQuery.data.dailyAveragePerUser)}건
              </span>
            </div>
            <div className="flex flex-1 flex-col gap-2 rounded-xl border border-border bg-card p-6">
              <span className="text-sm text-muted-foreground">사용자 1인당 월간 평균 메시지 전송 수</span>
              <span className="text-3xl font-bold tabular-nums text-foreground">
                {formatAverage(usageMetricsQuery.data.monthlyAveragePerUser)}건
              </span>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-6">
            <h2 className="mb-4 text-sm font-medium text-foreground">전체 메시지 전송량 추이</h2>
            <ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
              <LineChart data={usageMetricsQuery.data.trend} margin={{ left: 8, right: 8 }}>
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
                  dataKey="messageCount"
                  type="monotone"
                  stroke="var(--color-messageCount)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ChartContainer>
          </div>
        </>
      )}
    </main>
  );
}
