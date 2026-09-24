import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { UsageMetricsPage } from "../pages/usage-metrics";

const isoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

const usageMetricsSearchSchema = z.object({
  from: isoDateSchema.optional().catch(undefined),
  to: isoDateSchema.optional().catch(undefined),
});

function toIsoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function defaultDateRange() {
  const to = new Date();
  const from = new Date(to);
  from.setDate(from.getDate() - 29);
  return { from: toIsoDate(from), to: toIsoDate(to) };
}

export const Route = createFileRoute("/usage-metrics")({
  validateSearch: usageMetricsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  // 스프레드 병합(`{ ...defaults, ...search }`) 금지: `.catch(undefined)`는 잘못된 값의 키를
  // 남기고 값만 undefined로 주므로 기본값을 덮는다. 필드별 `??`로 채운다.
  const defaults = defaultDateRange();
  const from = search.from ?? defaults.from;
  const to = search.to ?? defaults.to;

  return (
    <UsageMetricsPage
      from={from}
      to={to}
      onRangeChange={(next) => void navigate({ search: (prev) => ({ ...prev, ...next }) })}
    />
  );
}
