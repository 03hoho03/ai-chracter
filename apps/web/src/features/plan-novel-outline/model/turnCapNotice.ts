import { toOverCapPhrase, toTurnCapFit, type ChapterTurnCap, type NovelOutlineView } from "@/entities/novel";
import { isApiError } from "@/shared/api/client";

import { countBasisTurns, type OutlineEpisodeDraft, type TurnIndex } from "./outlineEdits";

/** 구성안 화 하나의 턴 상한 안내. `partial` 은 일부 모델만 못 쓰는 화(다른 모델로는 쓸 수 있어 오류가 아니다), `blocking` 은 이 계정이
 * 고를 수 있는 어느 모델로도 못 쓰는 화(서버가 이런 화가 있는 구성안의 승인을 막는다). */
export type TurnCapNotice = { tone: "partial" | "blocking"; message: string };

/** 화마다 턴 수(근거 안 모델 응답 수). 대화를 받았으면 화면이 근거로 센다 — 저장 전 화(나눈 조각·합친 결과)도 서버와 같은 수다. 대화를
 * 아직 못 받았으면 근거가 서버 판과 같은 화만 서버 값(`turnCount`)을 쓰고, 고친 화·나눈 화는 모른다. */
export function toEpisodeTurnCounts(
  episodes: readonly OutlineEpisodeDraft[],
  index: TurnIndex | undefined,
  view: NovelOutlineView | undefined,
): (number | undefined)[] {
  return episodes.map((episode) => {
    if (index !== undefined) return countBasisTurns(index, episode.basis);
    const saved = view?.episodes.find((item) => item.key === episode.key);
    if (saved === undefined || !isSameBasis(saved.basis, episode.basis)) return undefined;
    return saved.turnCount ?? undefined;
  });
}

function isSameBasis(
  a: readonly { startMessageId: string; endMessageId: string }[],
  b: readonly { startMessageId: string; endMessageId: string }[],
): boolean {
  return (
    a.length === b.length &&
    a.every((range, index) => range.startMessageId === b[index]?.startMessageId && range.endMessageId === b[index]?.endMessageId)
  );
}

/** 화 하나의 턴 상한 안내. 상한 안이거나 턴 수·상한 목록을 모르면 없다. */
export function toEpisodeTurnCapNotice(turnCount: number | undefined, caps: readonly ChapterTurnCap[]): TurnCapNotice | undefined {
  const fit = toTurnCapFit(turnCount, caps);
  if (fit === undefined || turnCount === undefined || fit.kind === "fits") return undefined;
  const turns = `${turnCount.toLocaleString()}턴`;
  if (fit.kind === "some") {
    return {
      tone: "partial",
      message: `이 화는 ${turns}이라 원고는 ${fit.ableNames.join("·")} 로만 쓸 수 있어요(${toOverCapPhrase(fit.over)}).`,
    };
  }
  return {
    tone: "blocking",
    message: `이 화는 ${turns}이라 어느 모델로도 원고를 쓸 수 없어요(${fit.maxTurns.toLocaleString()}턴까지). 나눈 뒤 승인할 수 있어요.`,
  };
}

type EpisodeTurns = { ordinal: number; turnCount: number | undefined; isWritten: boolean };

/** "이대로 승인"을 누르기 전에 막을 이유 — 원고가 없는 화 중 이 계정이 고를 수 있는 어느 모델의 상한보다도 긴 화. 서버의 승인 거절과
 * 같은 판정이다(원고가 된 화·셀 수 없는 화는 막지 않는다). 상한 목록이 없으면(그 칸을 싣기 전 서버) 막지 않는다. */
export function toApproveTurnCapBlock(episodes: readonly EpisodeTurns[], caps: readonly ChapterTurnCap[]): string | undefined {
  if (caps.length === 0) return undefined;
  const maxTurns = Math.max(...caps.map((cap) => cap.maxTurns));
  const over = episodes.flatMap((episode) =>
    !episode.isWritten && episode.turnCount !== undefined && episode.turnCount > maxTurns
      ? [{ ordinal: episode.ordinal, turnCount: episode.turnCount }]
      : [],
  );
  return over.length === 0 ? undefined : toTooLongEpisodesMessage(over, maxTurns);
}

function toTooLongEpisodesMessage(over: readonly { ordinal: number; turnCount: number }[], maxTurns: number): string {
  const max = maxTurns.toLocaleString();
  const [only] = over;
  if (over.length === 1 && only !== undefined) {
    return `${only.ordinal}화가 ${only.turnCount.toLocaleString()}턴이라 어느 모델로도 원고를 쓸 수 없어요(${max}턴까지). 나눈 뒤 승인해주세요.`;
  }
  const list = over.map((episode) => `${episode.ordinal}화(${episode.turnCount.toLocaleString()}턴)`).join("·");
  return `${list}가 ${max}턴을 넘어 어느 모델로도 원고를 쓸 수 없어요. 나눈 뒤 승인해주세요.`;
}

/** 승인 409 `NOVEL_OUTLINE_EPISODE_TOO_LONG` 의 문구 — 서버가 짚은 화 키를 지금 화면의 화 번호로 바꿔 말한다. 짚은 화를 하나라도 못
 * 찾으면(그사이 구성안이 바뀜) 화 번호 없이 말한다. 이 거절이 아니면 `undefined`. */
export function toTooLongApprovalMessage(
  error: unknown,
  episodes: readonly { key: string | null; ordinal: number }[],
): string | undefined {
  if (!isApiError(error)) return undefined;
  const detail: unknown = error.detail;
  if (!isRecord(detail) || detail.code !== "NOVEL_OUTLINE_EPISODE_TOO_LONG") return undefined;
  const maxTurns = typeof detail.maxTurns === "number" ? detail.maxTurns : undefined;
  const over = (Array.isArray(detail.episodes) ? detail.episodes : []).map((item: unknown) => {
    if (!isRecord(item) || typeof item.key !== "string" || typeof item.turnCount !== "number") return undefined;
    const key = item.key;
    const ordinal = episodes.find((episode) => episode.key === key)?.ordinal;
    return ordinal === undefined ? undefined : { ordinal, turnCount: item.turnCount };
  });
  const known = over.filter((item) => item !== undefined);
  if (maxTurns !== undefined && known.length > 0 && known.length === over.length) return toTooLongEpisodesMessage(known, maxTurns);
  const limit = maxTurns === undefined ? "" : `(${maxTurns.toLocaleString()}턴까지)`;
  return `어느 모델로도 원고를 쓸 수 없을 만큼 긴 화가 있어요${limit}. 나눈 뒤 승인해주세요.`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
