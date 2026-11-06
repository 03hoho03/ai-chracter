import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { requireSession } from "../entities/session";
import { FEATURE_SWITCH_NAMES, FeatureSwitchesPage } from "../pages/feature-switches";

// 잘못된 값은 화면을 죽이는 대신 기본값으로 삼킨다. `switch` 는 이력 거르기 옵션(버튼으로 바꾸는 스위치) 밖의 값을 버린다 —
// 거르기 칸은 옵션에 없는 값을 "전체"로 보여, 그대로 두면 칸과 서버 질의가 어긋난다.
const featureSwitchesSearchSchema = z.object({
  page: z.coerce.number().int().min(1).optional().catch(undefined),
  switch: z.enum(FEATURE_SWITCH_NAMES).optional().catch(undefined),
});

export const Route = createFileRoute("/feature-switches")({
  validateSearch: featureSwitchesSearchSchema,
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: RouteComponent,
});

function RouteComponent() {
  const { page = 1, switch: historySwitch } = Route.useSearch();
  const navigate = Route.useNavigate();

  return (
    <FeatureSwitchesPage
      historySwitch={historySwitch}
      historyPage={page}
      onHistoryPageChange={(nextPage) =>
        void navigate({ search: (prev) => ({ ...prev, page: nextPage }), resetScroll: false })
      }
      onHistorySwitchChange={(nextSwitch) =>
        void navigate({ search: (prev) => ({ ...prev, switch: nextSwitch, page: undefined }), resetScroll: false })
      }
    />
  );
}
