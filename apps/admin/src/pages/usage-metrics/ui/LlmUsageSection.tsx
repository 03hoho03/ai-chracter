import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@ai-character-chat/ui/components/table";
import { ToggleGroup, ToggleGroupItem } from "@ai-character-chat/ui/components/toggle-group";
import { useState } from "react";

import { formatCount } from "@/shared/lib/format/formatCount";
import { DenseTable } from "@/shared/ui/DenseTable";

import { useLlmUsageQuery, type AdminLlmUsageResponse, type AdminLlmUsageRow } from "../api/useLlmUsageQuery";

type LlmUsageView = "total" | "daily";

// 운영자가 읽는 이름. 서버의 call_site 목록과 따로 관리되므로, 여기 없는 값은 원래 이름만 보인다.
const CALL_SITE_LABELS: Record<string, string> = {
  chat_generate: "채팅 생성",
  chat_stat_judgment: "채팅 스탯 판정",
  chat_ending_judgment: "채팅 엔딩 판정",
  chat_situational_image: "상황 이미지 판정",
  chat_media_book_image: "미디어 북 칸 판정",
  chat_memory_summary: "기억 요약",
  preview_generate: "미리보기 생성",
  preview_stat_judgment: "미리보기 스탯 판정",
  preview_ending_judgment: "미리보기 엔딩 판정",
  preview_media_book_image: "미리보기 미디어 북 판정",
  publish_filter_character: "발행 심사(캐릭터)",
  publish_filter_story: "발행 심사(스토리)",
  seed_story_generate: "시드 스토리 생성",
  seed_similarity_review: "시드 유사도 심사",
};

const CELL_CLASS = "text-right tabular-nums";
const HEAD_START_CLASS = "text-muted-foreground";
const HEAD_CELL_CLASS = "text-right text-muted-foreground";

function formatUsd(value: number) {
  // 호출 몇 건의 원가는 1센트에 못 미쳐 소수 둘째 자리에서 0 으로 뭉개진다 — 1달러 미만은 넷째 자리까지.
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  });
}

function formatRate(value: number | null) {
  return value === null ? "–" : `${(value * 100).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`;
}

type LlmUsageSectionProps = {
  from: string;
  to: string;
};

/** 집계 단위 토글은 이 표 하나만 바꾸므로 로컬 state로 둔다(새로고침하면 기간 합계로 돌아간다). */
export function LlmUsageSection({ from, to }: LlmUsageSectionProps) {
  const [view, setView] = useState<LlmUsageView>("total");

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-foreground">LLM 사용량</h2>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={view}
            aria-label="LLM 사용량 집계 단위"
            onValueChange={(value) => {
              // 선택된 칩을 다시 누르면 Radix가 `""`를 보낸다 — 단일선택이라 무시한다.
              if (value === "total" || value === "daily") setView(value);
            }}
          >
            <ToggleGroupItem value="total">기간 합계</ToggleGroupItem>
            <ToggleGroupItem value="daily">일자별</ToggleGroupItem>
          </ToggleGroup>
        </div>
        {/* 같은 기간 입력을 위 메시지 지표와 함께 쓰지만 하루를 자르는 기준이 달라, 두 숫자를 나란히
         * 읽을 때 생기는 어긋남을 화면에서 밝힌다. */}
        <p className="text-xs text-muted-foreground">
          날짜는 한국 시간(KST) 기준이라 위 메시지 지표(UTC 기준)와 하루 경계가 9시간 어긋납니다. 응답을
          받은 호출만 세며, 최대 92일까지 볼 수 있습니다.
        </p>
      </div>
      <LlmUsageBody from={from} to={to} view={view} />
    </section>
  );
}

type LlmUsageBodyProps = LlmUsageSectionProps & { view: LlmUsageView };

/** 섹션 머리(제목·토글·안내)는 로딩·에러에도 남아야 해서 쿼리에 의존하는 본문만 갈라낸다. */
function LlmUsageBody({ from, to, view }: LlmUsageBodyProps) {
  const llmUsageQuery = useLlmUsageQuery({ from, to });

  if (llmUsageQuery.isPending) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" />;
  }

  if (llmUsageQuery.isError) {
    return (
      <p className="text-sm text-destructive-text">
        {llmUsageQuery.error.status === 400
          ? "LLM 사용량은 한 번에 92일까지 볼 수 있어요. 기간을 줄여주세요."
          : "LLM 사용량을 불러오지 못했어요. 잠시 후 다시 시도해주세요."}
      </p>
    );
  }

  const data = llmUsageQuery.data;

  return (
    <>
      <CostSummary data={data} />
      {data.totals.length === 0 ? (
        <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          이 기간에 기록된 LLM 호출이 없어요. 호출이 일어나면 한국 시간 하루 단위로 쌓입니다.
        </p>
      ) : (
        <UsageTable rows={view === "total" ? data.totals : newestDayFirst(data.rows)} showDay={view === "daily"} />
      )}
      <Definitions data={data} />
    </>
  );
}

function newestDayFirst(rows: AdminLlmUsageRow[]) {
  // 서버는 날짜 오름차순 + 날짜 안에서 call_site 순으로 준다. 정렬이 안정적이라 날짜 안 순서는 유지된다.
  return [...rows].sort((a, b) => (b.day ?? "").localeCompare(a.day ?? ""));
}

function CostSummary({ data }: { data: AdminLlmUsageResponse }) {
  return (
    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm text-muted-foreground">
      기간 추정 원가
      <span className="text-lg font-semibold tabular-nums text-foreground">{formatUsd(data.estimatedCostUsdTotal)}</span>
      {data.unpricedCalls > 0 && (
        <span className="text-xs">단가표에 없는 모델의 호출 {formatCount(data.unpricedCalls)}건은 빠진 금액입니다.</span>
      )}
    </p>
  );
}

type UsageTableProps = {
  rows: AdminLlmUsageRow[];
  showDay: boolean;
};

// 열이 많아 좁은 화면에선 가로로 스크롤되고, 첫 열(일자 또는 호출 위치)은 왼쪽에 고정된다. 매일 보는 숫자(호출·판정
// 비율·캐시 적중·원가)를 앞에 두고 원 토큰 수는 뒤로 미룬다.
function UsageTable({ rows, showDay }: UsageTableProps) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <DenseTable surface="card">
        <Table>
          <caption className="sr-only">
            {showDay ? "일자(KST)" : "기간 합계"} 호출 위치·모델별 LLM 호출 수, 토큰, 캐시 적중률, 판정 비율, 추정 원가.
          </caption>
          <TableHeader>
            <TableRow>
              {showDay && <TableHead className={HEAD_START_CLASS}>일자</TableHead>}
              <TableHead className={HEAD_START_CLASS}>호출 위치</TableHead>
              <TableHead className={HEAD_START_CLASS}>모델</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>호출</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>판정 비율</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>캐시 적중</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>추정 원가</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>입력</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>캐시</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>출력</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>사고</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>합계</TableHead>
              <TableHead className={HEAD_CELL_CLASS}>입력 미보고</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={`${row.day ?? "total"}|${row.callSite}|${row.model}`}>
                {showDay && <TableCell className="tabular-nums text-foreground">{row.day}</TableCell>}
                <TableCell>
                  <span className="text-foreground">{CALL_SITE_LABELS[row.callSite] ?? row.callSite}</span>
                  {CALL_SITE_LABELS[row.callSite] && (
                    <span className="block text-xs text-muted-foreground">{row.callSite}</span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{row.model}</TableCell>
                <TableCell className={`${CELL_CLASS} text-foreground`}>{formatCount(row.calls)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatRate(row.judgmentRatio)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatRate(row.cacheHitRate)}</TableCell>
                <TableCell className={`${CELL_CLASS} text-foreground`}>
                  {row.estimatedCostUsd === null ? (
                    <span className="text-muted-foreground">단가 없음</span>
                  ) : (
                    formatUsd(row.estimatedCostUsd)
                  )}
                </TableCell>
                <TableCell className={CELL_CLASS}>{formatCount(row.inputTokens)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatCount(row.cachedTokens)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatCount(row.outputTokens)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatCount(row.thoughtsTokens)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatCount(row.totalTokens)}</TableCell>
                <TableCell className={CELL_CLASS}>{formatCount(row.missingCalls)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DenseTable>
    </div>
  );
}

/** 열의 정의와 단가표. 숫자를 잘못 읽기 쉬운 지점(정상 판정 비율이 100%가 아님, 보고된 캐시 적중이
 * 청구 할인과 다름, 손으로 옮긴 단가가 낡음)을 표 바로 아래에서 밝힌다. 매일 읽는 글이 아니라 숫자가 이상할 때 찾아보는
 * 글이라 기본으로 접어 둔다 — 펼쳐 두면 표보다 긴 글 벽이 화면을 차지한다. */
function Definitions({ data }: { data: AdminLlmUsageResponse }) {
  return (
    <details className="text-xs text-muted-foreground">
      {/* 손가락 포인터에서는 한 줄(16px) 위아래로 12px 를 더해 누르는 높이를 40px 로 올린다. */}
      <summary className="w-fit cursor-pointer rounded-sm font-medium outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:py-3">
        열 정의와 단가표
      </summary>
      <dl className="mt-3 grid max-w-3xl gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr]">
        <dt className="font-medium text-foreground">판정 비율</dt>
        <dd>
          판정 호출 수 ÷ 같은 날 생성 호출 수(채팅 판정은 채팅 생성, 미리보기 판정은 미리보기 생성 기준, 모델
          합). 엔딩은 정해진 턴에 스탯 조건까지 맞을 때만, 미디어 북 판정은 미디어 북이 있는 작품에만 돌아
          정상값도 100%가 아닙니다. 응답을 못 받은 실패(없는 모델·429·네트워크 오류)는 세지 않으므로 평소보다
          갑자기 떨어지면 판정이 조용히 빠지고 있다는 신호입니다. 응답은 왔지만 형식이 틀려 버려진 판정은 정상
          호출과 똑같이 세어져 비율에 드러나지 않습니다. 이 실패는 Bugsink 에서 dependency=gemini 태그의
          “could not be parsed” 이벤트로 봅니다.
        </dd>
        <dt className="font-medium text-foreground">캐시 적중</dt>
        <dd>캐시 ÷ 보고된 입력 토큰. 모델이 보고한 적중이며 청구 할인으로 확인된 값은 아닙니다.</dd>
        <dt className="font-medium text-foreground">입력 미보고</dt>
        <dd>
          입력 토큰 없이 응답한 호출 수(이미지가 실린 호출). 입력 열은 이 호출의 입력을 합계 − 출력 − 사고로
          복원해 더한 값입니다.
        </dd>
        <dt className="font-medium text-foreground">추정 원가</dt>
        <dd>
          아래 단가표(USD / 100만 토큰, {data.pricesAsOf} 확인)로 계산한 추정치입니다. 사고 토큰은 출력 단가로
          셉니다. 단가는 손으로 옮긴 값이라 가격이 바뀌어도 따라오지 않고, 표에 없는 모델은 단가 없음으로
          비웁니다.
          <ul className="mt-1 flex flex-col gap-0.5 tabular-nums">
            {data.prices.map((price) => (
              <li key={price.model}>
                {price.model} — 입력 {price.inputUsdPerMillion} · 캐시 {price.cachedInputUsdPerMillion} · 출력{" "}
                {price.outputUsdPerMillion}
              </li>
            ))}
          </ul>
        </dd>
      </dl>
    </details>
  );
}
