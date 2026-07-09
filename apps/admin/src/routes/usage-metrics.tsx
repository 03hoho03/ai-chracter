import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { UsageMetricsPage } from "../pages/usage-metrics";

const isoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);

const usageMetricsSearchSchema = z.object({
  from: isoDateSchema.optional(),
  to: isoDateSchema.optional(),
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
  const { from, to } = { ...defaultDateRange(), ...search };

  return (
    <UsageMetricsPage
      from={from}
      to={to}
      onRangeChange={(next) => void navigate({ search: (prev) => ({ ...prev, ...next }) })}
    />
  );
}
