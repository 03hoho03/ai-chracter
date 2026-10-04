import { PageContainer } from "@/shared/ui/PageContainer";

import { ActivityFeed } from "./ActivityFeed";
import { CohortTable } from "./CohortTable";
import { CountCards } from "./CountCards";
import { GrowthCards } from "./GrowthCards";
import { PopularList } from "./PopularList";
import { TrendChart } from "./TrendChart";

/** 각 영역이 자기 로딩·에러를 렌더한다 — 여기서는 전체를 막는 조기 반환을
 * 하지 않는다. 하나가 500을 내도 나머지 영역은 정상 표시돼야 한다.
 *
 * 영역들을 감싼 `@container` 가 카드·차트 그리드의 열 수를 정한다 — 사이드바가 펴지고 접히면 같은 뷰포트에서도 본문
 * 폭이 달라져, 뷰포트 브레이크포인트로 가르면 카드 라벨이 꺾이고 차트가 짓눌린다. */
export function DashboardPage() {
  return (
    <PageContainer>
      <h1 className="text-2xl font-bold tracking-tight text-foreground">대시보드</h1>

      <div className="@container flex flex-col gap-6">
        <CountCards />
        <TrendChart />

        {/* 성장 지표는 `PRODUCT.md`가 선언한 성공 기준(가입자→첫 대화, 제작자→발행)을
         * 그대로 옮긴 것이다. 유지율 표는 전체/베타 토글이 있어 카드의 `/growth`가 아니라 전용
         * 엔드포인트를 따로 부른다(`/growth`의 다른 지표는 베타로 거르지 않는다). */}
        <GrowthCards />
        <CohortTable />

        {/* PopularList는 5개 컬럼(이름·타입·채팅수·조회수·좋아요수)을 갖고 있어 절반 폭
         * 2단 그리드에 넣으면 넓은 컬럼이 카드 밖으로 밀린다 — 전체 폭 스택으로 둔다. */}
        <PopularList />
        <ActivityFeed />
      </div>
    </PageContainer>
  );
}
