import { ActivityFeed } from "./ActivityFeed";
import { CohortTable } from "./CohortTable";
import { CountCards } from "./CountCards";
import { GrowthCards } from "./GrowthCards";
import { PopularList } from "./PopularList";
import { TrendChart } from "./TrendChart";

/** 각 영역이 자기 로딩·에러를 렌더한다 — 여기서는 전체를 막는 조기 반환을
 * 하지 않는다. 하나가 500을 내도 나머지 영역은 정상 표시돼야 한다. */
export function DashboardPage() {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight text-foreground">대시보드</h1>

      <CountCards />
      <TrendChart />

      {/* 성장 지표는 `PRODUCT.md`가 선언한 성공 기준(가입자→첫 대화, 제작자→발행)을
       * 그대로 옮긴 것이다. 카드와 표가 `useGrowthQuery` 하나를 공유한다(요청 1개). */}
      <GrowthCards />
      <CohortTable />

      {/* PopularList는 5개 컬럼(이름·타입·채팅수·조회수·좋아요수)을 갖고 있어 절반 폭
       * 2단 그리드에 넣으면 넓은 컬럼이 카드 밖으로 밀린다 — 전체 폭 스택으로 둔다. */}
      <PopularList />
      <ActivityFeed />
    </main>
  );
}
