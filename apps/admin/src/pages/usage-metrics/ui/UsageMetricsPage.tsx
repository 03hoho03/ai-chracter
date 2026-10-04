import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@ai-character-chat/ui/components/chart";
import { Input } from "@ai-character-chat/ui/components/input";
import { Label } from "@ai-character-chat/ui/components/label";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { useUsageMetricsQuery } from "@/entities/usage-metrics";
import { CHART_FOCUS_CLASS } from "@/shared/ui/chartFocusClass";
import { PageContainer } from "@/shared/ui/PageContainer";
import { PageHeader } from "@/shared/ui/PageHeader";

import { LlmUsageSection } from "./LlmUsageSection";

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

type UsageMetricsPageProps = {
  from: string;
  to: string;
  onRangeChange: (range: Partial<{ from: string; to: string }>) => void;
}

export function UsageMetricsPage({ from, to, onRangeChange }: UsageMetricsPageProps) {
  const usageMetricsQuery = useUsageMetricsQuery({ from, to });

  return (
    <PageContainer>
      <PageHeader
        title="사용량 모니터링"
        actions={
          // 좁은 화면에서는 두 날짜 칸이 다음 줄로 넘어간다(날짜 입력은 브라우저마다 고유 폭이 있어 줄이지 않는다).
          <div className="flex flex-wrap items-end gap-3">
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
        }
      />

      {usageMetricsQuery.isPending && (
        <div className="h-64 animate-pulse rounded-xl bg-muted" />
      )}

      {usageMetricsQuery.isError && (
        <p className="text-sm text-destructive-text">
          사용량 지표를 불러오지 못했어요. 기간을 확인한 뒤 다시 시도해주세요.
        </p>
      )}

      {usageMetricsQuery.data && (
        <>
          {/* 라벨이 길어 한 줄에 둘을 두기 좁으면 카드가 다음 줄로 내려간다. */}
          <div className="flex flex-wrap gap-4">
            <div className="flex min-w-64 flex-1 flex-col gap-2 rounded-xl border border-border bg-card p-6">
              <span className="text-sm text-muted-foreground">사용자 1인당 일일 평균 메시지 전송 수</span>
              <span className="text-2xl font-bold tabular-nums text-foreground">
                {formatAverage(usageMetricsQuery.data.dailyAveragePerUser)}건
              </span>
            </div>
            <div className="flex min-w-64 flex-1 flex-col gap-2 rounded-xl border border-border bg-card p-6">
              <span className="text-sm text-muted-foreground">사용자 1인당 월간 평균 메시지 전송 수</span>
              <span className="text-2xl font-bold tabular-nums text-foreground">
                {formatAverage(usageMetricsQuery.data.monthlyAveragePerUser)}건
              </span>
            </div>
          </div>

          <div className={cn("rounded-xl border border-border bg-card p-6", CHART_FOCUS_CLASS)}>
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
                {/* 일 단위 정수라 점 사이를 곧게 잇는다 — 곡선 보간은 없는 값을 그린다. */}
                <Line
                  dataKey="messageCount"
                  type="linear"
                  stroke="var(--color-messageCount)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ChartContainer>
          </div>
        </>
      )}

      <LlmUsageSection from={from} to={to} />
    </PageContainer>
  );
}
