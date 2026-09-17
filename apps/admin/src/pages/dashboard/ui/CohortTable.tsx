import { formatCount } from "@/shared/lib/format/formatCount";

import { useGrowthQuery, type AdminDashboardCohort } from "../api/useGrowthQuery";

/** 코호트마다 관측된 주차 수가 다르다(이번 주 가입자는 W0 하나뿐). 헤더는 가장 긴
 * 코호트에 맞춰 그리고, 아직 오지 않은 주차는 0이 아니라 **빈 칸**으로 둔다 — API도 같은
 * 이유로 미관측 주차를 생략해서 준다("아직 유지 안 됨"과 "아직 관측 불가"는 다르다). */
function maxWeekOffset(cohorts: readonly AdminDashboardCohort[]) {
  return cohorts.reduce(
    (max, cohort) => cohort.weeks.reduce((inner, week) => Math.max(inner, week.weekOffset), max),
    0,
  );
}

function formatWeekStart(isoDate: string) {
  const [, month, day] = isoDate.split("-");
  return `${Number(month)}/${Number(day)}`;
}

const CELL_CLASS = "px-3 py-2 text-right tabular-nums whitespace-nowrap";
const HEAD_CELL_CLASS = "px-3 py-2 text-right font-medium whitespace-nowrap";

export function CohortTable() {
  return (
    <section>
      <h2 className="text-sm font-medium text-foreground">주별 유지율</h2>
      {/* 근사임을 화면에서 밝힌다 — 응답 스키마 주석은 코드를 읽는 사람만 본다. 이 한 줄이
       * 없으면 운영자가 정확한 재방문율로 읽는다. */}
      <p className="mt-1 mb-4 text-xs text-muted-foreground">
        재방문 기록이 없어 &lsquo;그 주에 메시지를 보냈는가&rsquo;로 갈음한 추정치입니다. 아직
        지나지 않은 주차는 비워 둡니다.
      </p>
      <CohortGrid />
    </section>
  );
}

/** 제목과 설명은 로딩·에러에도 남아야 해서 쿼리에 의존하는 표만 갈라낸다(TrendChart와 같은 꼴). */
function CohortGrid() {
  const growthQuery = useGrowthQuery();

  if (growthQuery.isPending) {
    return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  }

  if (growthQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        유지율을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const cohorts = growthQuery.data.cohortRetention;

  if (cohorts.length === 0) {
    return (
      <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
        아직 집계할 가입자가 없어요. 가입이 생기면 주 단위로 쌓입니다.
      </p>
    );
  }

  const weekOffsets = Array.from({ length: maxWeekOffset(cohorts) + 1 }, (_, index) => index);

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          가입 주차별 유지율. 행은 가입 주, 열은 가입 후 경과 주차입니다.
        </caption>
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th scope="col" className="px-3 py-2 text-left font-medium whitespace-nowrap">
              가입 주
            </th>
            <th scope="col" className={HEAD_CELL_CLASS}>
              인원
            </th>
            {weekOffsets.map((offset) => (
              <th key={offset} scope="col" className={HEAD_CELL_CLASS}>
                W{offset}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cohorts.map((cohort) => {
            const byOffset = new Map(cohort.weeks.map((week) => [week.weekOffset, week]));
            return (
              <tr key={cohort.cohortWeekStart} className="border-b border-border last:border-b-0">
                <th
                  scope="row"
                  className="px-3 py-2 text-left font-normal tabular-nums whitespace-nowrap text-foreground"
                >
                  {formatWeekStart(cohort.cohortWeekStart)}
                </th>
                <td className={`${CELL_CLASS} text-muted-foreground`}>
                  {formatCount(cohort.cohortSize)}
                </td>
                {weekOffsets.map((offset) => {
                  const week = byOffset.get(offset);
                  if (!week) {
                    return (
                      <td key={offset} className={CELL_CLASS}>
                        <span className="sr-only">아직 지나지 않은 주차</span>
                        <span aria-hidden="true" className="text-muted-foreground">
                          &ndash;
                        </span>
                      </td>
                    );
                  }
                  return (
                    <td key={offset} className={`${CELL_CLASS} text-foreground`}>
                      {Math.round(week.retentionRate * 100)}%
                      <span className="ml-1 text-xs text-muted-foreground">
                        ({formatCount(week.retainedUsers)})
                      </span>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
