import type { ReactNode } from "react";

import type { AttemptDetail, ReplyFlagsView, TurnDetail } from "@/shared/api/client";
import { cn } from "@/shared/lib/cn";
import { formatCount, formatMs } from "@/shared/lib/formatNumber";

import { BOOLEAN_FLAG_KEYS, BOOLEAN_FLAG_LABELS } from "../model/detailLabels";
import { readBoolean, readNumber, readText } from "../model/recordFields";
import { formatStatDelta, type StatDelta } from "../model/turnRows";
import { StatDot } from "./StatDot";

type ConversationPaneProps = {
  turn: number;
  turnDetail: TurnDetail;
  attempt: AttemptDetail | undefined;
  /** 보고 있는 시도의 Δ — 고른 시도는 턴 목록 행과 같고, 고르지 않은 시도는 그 시도의 드라이버 줄 변화다. */
  deltas: ReadonlyArray<StatDelta>;
  /** 앞 턴 상세를 흐리게 들고 있는 동안 — 시도 버튼을 누르면 앞 턴의 시도 번호가 새 턴에 적용되므로 막는다. */
  isStale: boolean;
  onSelectAttempt: (index: number) => void;
};

/** 턴 상세 머리와 대화 — 시도 전환, 플래그·Δ 칩, 사용자 발화, 응답 원문, 응답 교체. */
export function ConversationPane({ turn, turnDetail, attempt, deltas, isStale, onSelectAttempt }: ConversationPaneProps) {
  const record = attempt?.record;
  const flags = attempt?.selected ? turnDetail.metrics?.flags : undefined;

  return (
    <div className="space-y-3 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-title text-ink tabular-nums">턴 {turn}</h2>
        {turnDetail.attempts.length > 1 && (
          <div role="group" aria-label="시도" className="inline-flex rounded-md border border-border p-0.5">
            {turnDetail.attempts.map((candidate) => (
              <button
                key={candidate.index}
                type="button"
                aria-pressed={candidate.index === attempt?.index}
                disabled={isStale}
                onClick={() => onSelectAttempt(candidate.index)}
                className={cn(
                  "h-6 rounded-sm px-2 text-data whitespace-nowrap focus-visible:outline-2 focus-visible:outline-accent motion-safe:transition-colors",
                  candidate.index === attempt?.index
                    ? "bg-surface-raised font-medium text-accent"
                    : "text-ink-secondary enabled:hover:text-ink",
                )}
              >
                시도 {candidate.index}
                {candidate.selected && " · 고름"}
                {candidate.serverRejected && " · 거부"}
              </button>
            ))}
          </div>
        )}
        {turnDetail.supplemented && <Chip title="clientTurn 없는 사람 보충 줄">보충 줄</Chip>}
        {turnDetail.earlierGenerationDumps.length > 0 && (
          <Chip title="이 턴의 앞선 생성 덤프 — 어느 시도의 것인지 가르지 않는다. 원문 칸의 출처에서 연다.">
            앞선 생성 덤프 {turnDetail.earlierGenerationDumps.length}개
          </Chip>
        )}
        {flags &&
          BOOLEAN_FLAG_KEYS.filter((key) => flags[key]).map((key) => <Chip key={key}>{BOOLEAN_FLAG_LABELS[key]}</Chip>)}
        {flags?.broken != null && <Chip tone="danger">깨짐 · {flags.broken}</Chip>}
        {deltas.map((delta) => (
          <Chip key={`${delta.tone}:${delta.name}`} title={deltaTitle(delta)}>
            <StatDot tone={delta.tone} />
            {delta.name}
            <span className="tabular-nums">{formatStatDelta(delta)}</span>
            {delta.delta === undefined && <span className="text-ink-muted tabular-nums">→ {formatCount(delta.after)}</span>}
          </Chip>
        ))}
      </div>

      {record === undefined ? (
        <p className="text-data text-ink-muted">이 턴에는 시도가 없다.</p>
      ) : (
        <AttemptBody record={record} attempt={attempt} flags={flags} />
      )}

      {turnDetail.replacements.length > 0 && (
        <section aria-label="응답 교체" className="space-y-3 border-t border-border pt-3">
          <p className="text-data text-warn">
            응답 교체됨 — 이 턴의 응답을 재생성·수정한 줄 {turnDetail.replacements.length}개. 다음 턴 지표는 성공한 마지막 교체 뒤
            응답을 직전 응답으로 견준다.
          </p>
          {turnDetail.replacements.map((replacement, index) => (
            // 드라이버 파일 순서 그대로이고 바뀌지 않는다.
            <Replacement key={index} record={replacement} order={index + 1} />
          ))}
        </section>
      )}
    </div>
  );
}

type AttemptBodyProps = {
  record: Readonly<Record<string, unknown>>;
  attempt: AttemptDetail | undefined;
  /** 고른 시도의 응답 지표. 다른 시도의 응답은 지표 표본이 아니라 없다. */
  flags: ReplyFlagsView | undefined;
};

function AttemptBody({ record, attempt, flags }: AttemptBodyProps) {
  const userText = readText(record, "userText");
  const shortcut = readText(record, "shortcut");
  const reply = readText(record, "reply") ?? "";
  const failure = readText(record, "failure");
  const partialReply = readText(record, "partialReply");
  const http = readNumber(record, "http");
  const isDone = readBoolean(record, "done") === true;
  const seconds = readNumber(record, "seconds");
  const ttftMs = readNumber(record, "ttftMs");

  return (
    <>
      <div>
        <p className="text-label text-ink-muted">사용자</p>
        {userText !== undefined && userText !== "" ? (
          <p className="mt-1 max-w-reading text-reading font-medium whitespace-pre-wrap text-ink wrap-break-word">{userText}</p>
        ) : (
          <p className="mt-1 text-body text-ink-secondary">
            {shortcut !== undefined ? `단축어 · ${shortcut} (원문은 드라이버 줄에 남기지 않는다)` : "발화 기록 없음"}
          </p>
        )}
      </div>
      <div>
        <p className="flex flex-wrap gap-x-2 text-label text-ink-muted tabular-nums">
          <span>응답</span>
          {reply !== "" && <span>{formatCount(reply.length)}자</span>}
          {flags !== undefined && flags.statusBlockLength > 0 && <span>상태창 {formatCount(flags.statusBlockLength)}자</span>}
          {flags !== undefined && <span>{formatCount(flags.sentenceCount)}문장</span>}
          {http !== undefined && http !== 200 && <span className="text-danger">HTTP {http}</span>}
          {http === undefined && attempt !== undefined && !isDone && <span className="text-danger">HTTP 기록 없음</span>}
          {!isDone && <span className="text-danger">완료 없음</span>}
          {seconds !== undefined && <span>{seconds}초</span>}
          {ttftMs !== undefined && <span>첫 글자 {formatMs(ttftMs)}</span>}
        </p>
        {failure !== undefined && <p className="mt-1 text-data text-danger wrap-anywhere">{failure}</p>}
        {reply !== "" ? (
          <p className="mt-1 max-w-reading text-reading whitespace-pre-wrap text-ink wrap-break-word">{reply}</p>
        ) : (
          <p className="mt-1 text-body text-ink-muted">응답 없음</p>
        )}
        {partialReply !== undefined && partialReply !== "" && (
          <div className="mt-2">
            <p className="text-label text-ink-muted">끊긴 조각 — 완료 없이 끝난 시도가 받은 데까지(지표에 쓰지 않는다)</p>
            <p className="mt-1 max-w-reading text-reading whitespace-pre-wrap text-ink-secondary wrap-break-word">
              {partialReply}
            </p>
          </div>
        )}
      </div>
    </>
  );
}

function Replacement({ record, order }: { record: Readonly<Record<string, unknown>>; order: number }) {
  const kind = readText(record, "kind");
  const reply = readText(record, "reply") ?? "";
  const http = readNumber(record, "http");
  const isDone = readBoolean(record, "done") === true;
  const failure = readText(record, "failure");
  const userText = readText(record, "userText");
  const label = replacementLabel(kind);

  return (
    <div>
      <p className="flex flex-wrap gap-x-2 text-label text-ink-muted tabular-nums">
        <span className="text-ink-secondary">
          {label} {order}
        </span>
        {reply !== "" && <span>{formatCount(reply.length)}자</span>}
        {http !== undefined && http !== 200 && <span className="text-danger">HTTP {http}</span>}
        {!isDone && <span className="text-danger">완료 없음</span>}
      </p>
      {kind === "edit" && userText !== undefined && (
        <p className="mt-1 max-w-reading text-body text-ink-secondary wrap-break-word">고친 발화 · {userText}</p>
      )}
      {failure !== undefined && <p className="mt-1 text-data text-danger wrap-anywhere">{failure}</p>}
      {reply !== "" && (
        <p className="mt-1 max-w-reading text-reading whitespace-pre-wrap text-ink wrap-break-word">{reply}</p>
      )}
    </div>
  );
}

/** Δ 칩에 마우스를 올리면 보이는 시작 값 → 바뀐 뒤 값. 시작 값을 모르면 그렇다고 적는다. */
function deltaTitle(delta: StatDelta): string {
  if (delta.before === undefined) return `그 턴이 시작한 값을 기록으로 알 수 없다 — 바뀐 뒤 값 ${formatCount(delta.after)}`;
  return `${formatCount(delta.before)} → ${formatCount(delta.after)}`;
}

function replacementLabel(kind: string | undefined): string {
  if (kind === "edit") return "수정";
  if (kind === "regenerate") return "재생성";
  return kind ?? "교체";
}

type ChipProps = {
  tone?: "quiet" | "danger";
  title?: string;
  children: ReactNode;
};

function Chip({ tone = "quiet", title, children }: ChipProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-[18px] items-center gap-1 rounded-sm bg-surface-raised px-1.5 text-label whitespace-nowrap",
        tone === "danger" ? "text-danger" : "text-ink-secondary",
      )}
    >
      {children}
    </span>
  );
}
