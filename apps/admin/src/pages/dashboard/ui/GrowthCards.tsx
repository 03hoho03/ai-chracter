import { formatCount } from "@/shared/lib/format/formatCount";

import { useGrowthQuery, type AdminDashboardGrowthResponse } from "../api/useGrowthQuery";

const CARD_CLASS = "flex flex-1 flex-col gap-1 rounded-xl border border-border bg-card p-6";
const RATE_CLASS = "text-xl font-bold tabular-nums text-foreground";
const GRID_CLASS = "grid grid-cols-2 gap-4 sm:grid-cols-4";

/** 비율만 크게 띄우면 "34%"가 몇 명 기준인지 알 수 없다 — 운영자에게는 분자·분모가 더
 * 쓸모 있고(11명 중 4명), 표본이 작을 때 비율이 과장돼 보이는 것도 여기서 드러난다. */
function formatRate(rate: number) {
  return `${Math.round(rate * 100)}%`;
}

type GrowthCard = {
  readonly label: string;
  readonly rate: (data: AdminDashboardGrowthResponse) => number;
  readonly numerator: (data: AdminDashboardGrowthResponse) => number;
  readonly denominator: (data: AdminDashboardGrowthResponse) => number;
  /** 분모가 무엇인지 카드마다 밝힌다 — 탈퇴율만 `totalSignups`(탈퇴자 포함) 기준이라
   * 탈퇴가 생기면 다른 카드와 모수가 달라진다. "11명 중"만 쓰면 같은 수처럼 읽힌다. */
  readonly denominatorLabel: string;
};

/** `PRODUCT.md`가 성공 지표로 선언한 둘(첫 대화 도달률·발행 완료율)이 앞에 오고, 그 둘을
 * 읽을 때 같이 봐야 하는 모수 지표(제작자 비율·탈퇴율)가 뒤따른다. */
const CARDS = [
  {
    label: "첫 대화 도달률",
    rate: (d) => d.activationRate,
    numerator: (d) => d.activatedUsers,
    denominator: (d) => d.totalUsers,
    denominatorLabel: "활동 회원",
  },
  {
    label: "발행 완료율",
    rate: (d) => d.publishRate,
    numerator: (d) => d.creatorsWithPublishedContent,
    denominator: (d) => d.totalUsers,
    denominatorLabel: "활동 회원",
  },
  {
    label: "제작자 비율",
    rate: (d) => d.creatorRate,
    numerator: (d) => d.usersWithContent,
    denominator: (d) => d.totalUsers,
    denominatorLabel: "활동 회원",
  },
  {
    label: "탈퇴율",
    rate: (d) => d.withdrawnRate,
    numerator: (d) => d.withdrawnUsers,
    denominator: (d) => d.totalSignups,
    denominatorLabel: "전체 가입",
  },
] as const satisfies readonly GrowthCard[];

/** 비율 4장. 이 영역만 실패해도 대시보드의 다른 영역은 각자 독립적으로 렌더된다. */
export function GrowthCards() {
  return (
    <section>
      {/* 제목이 없으면 위쪽 `CountCards`(총 유저·총 작품…)와 구분되지 않아 "카드 4장이 또
       * 나왔다"로 읽힌다 — 실제 화면에서 확인하고 추가했다. */}
      <h2 className="mb-4 text-sm font-medium text-foreground">성장 지표</h2>
      <GrowthCardGrid />
    </section>
  );
}

/** 제목은 로딩·에러에도 남아야 해서 쿼리에 의존하는 그리드만 갈라낸다(TrendChart와 같은 꼴). */
function GrowthCardGrid() {
  const growthQuery = useGrowthQuery();

  if (growthQuery.isPending) {
    return (
      <div className={GRID_CLASS}>
        {CARDS.map(({ label }) => (
          <div key={label} className="h-24 animate-pulse rounded-xl bg-muted" />
        ))}
      </div>
    );
  }

  if (growthQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        성장 지표를 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const data = growthQuery.data;

  return (
    <div className={GRID_CLASS}>
      {CARDS.map(({ label, rate, numerator, denominator, denominatorLabel }) => (
        <div key={label} className={CARD_CLASS}>
          <span className="text-sm text-muted-foreground">{label}</span>
          <span className={RATE_CLASS}>{formatRate(rate(data))}</span>
          <span className="text-xs tabular-nums text-muted-foreground">
            {denominatorLabel} {formatCount(denominator(data))}명 중 {formatCount(numerator(data))}명
          </span>
        </div>
      ))}
    </div>
  );
}
