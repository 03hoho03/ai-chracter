import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useState } from "react";

import { formatCount } from "@/shared/lib/format/formatCount";
import { DenseTable } from "@/shared/ui/DenseTable";

import { useCohortRetentionQuery } from "../api/useCohortRetentionQuery";
import type { AdminDashboardCohort } from "../api/useGrowthQuery";

type CohortMode = "all" | "beta";

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

const CELL_CLASS = "text-right tabular-nums";
const HEAD_CELL_CLASS = "text-right text-muted-foreground";

/** 전체/베타 토글은 이 표 하나만 바꾸므로 로컬 state로 둔다(새로고침하면 전체로 돌아간다). */
export function CohortTable() {
  const [mode, setMode] = useState<CohortMode>("all");

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">주별 유지율</h2>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={mode}
          aria-label="유지율 집계 대상"
          onValueChange={(value) => {
            // 선택된 칩을 다시 누르면 Radix가 `""`를 보낸다 — 단일선택이라 무시한다.
            if (value === "all" || value === "beta") setMode(value);
          }}
        >
          <ToggleGroupItem value="all">전체</ToggleGroupItem>
          <ToggleGroupItem value="beta">베타 참가자</ToggleGroupItem>
        </ToggleGroup>
      </div>
      {/* 근사임을 화면에서 밝힌다 — 응답 스키마 주석은 코드를 읽는 사람만 본다. 이 한 줄이
       * 없으면 운영자가 정확한 재방문율로 읽는다. 베타 모드는 묶는 기준이 달라 그것도 밝힌다. */}
      <p className="mt-1 mb-4 text-xs text-muted-foreground">
        재방문 기록이 없어 &lsquo;그 주에 메시지를 보냈는가&rsquo;로 갈음한 추정치입니다. 아직
        지나지 않은 주차는 비워 둡니다.
        {mode === "beta" && " 베타 참가자만 베타로 지정된 주로 묶고, 지정 전 메시지는 세지 않습니다."}
      </p>
      <CohortGrid mode={mode} />
    </section>
  );
}

const COHORT_HEAD_LABEL: Record<CohortMode, string> = { all: "가입 주", beta: "지정 주" };

const COHORT_CAPTION: Record<CohortMode, string> = {
  all: "가입 주차별 유지율. 행은 가입 주, 열은 가입 후 경과 주차입니다.",
  beta: "베타 지정 주차별 유지율. 행은 베타로 지정된 주, 열은 지정 후 경과 주차입니다.",
};

const EMPTY_MESSAGE: Record<CohortMode, string> = {
  all: "아직 집계할 가입자가 없어요. 가입이 생기면 주 단위로 쌓입니다.",
  beta: "아직 베타 참가자가 없어요. 유저 상세에서 베타로 지정하면 지정한 주부터 쌓입니다.",
};

/** 제목과 설명은 로딩·에러에도 남아야 해서 쿼리에 의존하는 표만 갈라낸다(TrendChart와 같은 꼴). */
function CohortGrid({ mode }: { mode: CohortMode }) {
  const cohortQuery = useCohortRetentionQuery(mode === "beta");

  if (cohortQuery.isPending) {
    return <div className="h-40 animate-pulse rounded-xl bg-muted" />;
  }

  if (cohortQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        유지율을 불러오지 못했어요. 잠시 후 다시 시도해주세요.
      </p>
    );
  }

  const cohorts = cohortQuery.data;

  if (cohorts.length === 0) {
    return (
      <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
        {EMPTY_MESSAGE[mode]}
      </p>
    );
  }

  const weekOffsets = Array.from({ length: maxWeekOffset(cohorts) + 1 }, (_, index) => index);

  // 공용 `Table` 의 래퍼가 가로 스크롤 상자이자 위치 기준(`relative`)이다. 손으로 짠 `overflow-x-auto` 상자는 위치
  // 기준이 아니어서, 빈 주차 칸의 화면 밖 읽기용 글자(`sr-only`, absolute)가 상자를 빠져나가 좁은 화면의 문서를 가로로
  // 넓혔다(390px 에서 문서 폭 802px).
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <DenseTable surface="card">
        <Table>
          <caption className="sr-only">{COHORT_CAPTION[mode]}</caption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col" className="text-muted-foreground">
                {COHORT_HEAD_LABEL[mode]}
              </TableHead>
              <TableHead scope="col" className={HEAD_CELL_CLASS}>
                인원
              </TableHead>
              {weekOffsets.map((offset) => (
                <TableHead key={offset} scope="col" className={HEAD_CELL_CLASS}>
                  W{offset}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {cohorts.map((cohort) => {
              const byOffset = new Map(cohort.weeks.map((week) => [week.weekOffset, week]));
              return (
                <TableRow key={cohort.cohortWeekStart}>
                  <th scope="row" className="p-2 text-left font-normal tabular-nums whitespace-nowrap text-foreground">
                    {formatWeekStart(cohort.cohortWeekStart)}
                  </th>
                  <TableCell className={`${CELL_CLASS} text-muted-foreground`}>{formatCount(cohort.cohortSize)}</TableCell>
                  {weekOffsets.map((offset) => {
                    const week = byOffset.get(offset);
                    if (!week) {
                      return (
                        <TableCell key={offset} className={CELL_CLASS}>
                          <span className="sr-only">아직 지나지 않은 주차</span>
                          <span aria-hidden="true" className="text-muted-foreground">
                            &ndash;
                          </span>
                        </TableCell>
                      );
                    }
                    return (
                      <TableCell key={offset} className={`${CELL_CLASS} text-foreground`}>
                        {Math.round(week.retentionRate * 100)}%
                        <span className="ml-1 text-xs text-muted-foreground">({formatCount(week.retainedUsers)})</span>
                      </TableCell>
                    );
                  })}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DenseTable>
    </div>
  );
}
