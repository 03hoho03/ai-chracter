import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { AppealsListPage } from "../pages/appeals";

const appealsSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional(),
  status: z.enum(["pending", "resolved"]).optional(),
});

export const Route = createFileRoute("/appeals")({
  validateSearch: appealsSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, status } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <AppealsListPage
      page={page}
      status={status}
      onPageChange={(nextPage) => void navigate({ search: (prev) => ({ ...prev, page: nextPage }) })}
      onStatusChange={(nextStatus) =>
        void navigate({ search: (prev) => ({ ...prev, status: nextStatus, page: 1 }) })
      }
    />
  );
}
