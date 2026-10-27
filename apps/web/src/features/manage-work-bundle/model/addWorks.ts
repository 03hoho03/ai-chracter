import { WORK_BUNDLE_MAX_ITEMS } from "@/entities/work";

import { toWorkBundleActionError, type WorkBundleActionError } from "./bundleActionError";

export type AddWorksResult = {
  added: number;
  /** 그사이 지워졌거나 넣을 수 없게 된 작품 — 건너뛰고 다음 작품으로 간다. */
  gone: number;
  /** 다 보내기 전에 멈춘 이유. 끝까지 보냈으면 `undefined`. */
  stoppedBy: "itemLimit" | "bundleGone" | "reconsent" | "failed" | undefined;
  /** 멈추게 한 실패 그대로 — 재동의 실패는 호출부가 다시 던져 전역 재동의 처리를 탄다. */
  stopError: unknown;
};

/**
 * 고른 작품을 하나씩 순서대로 넣는다(서버에 일괄 넣기가 없다). 넣기는 멱등이라 이미 든 작품을 다시 보내도 안전하고,
 * 멈춘 뒤 다시 눌러도 이미 넣은 것은 그대로다.
 *
 * 넣을 수 없는 작품 하나는 건너뛴다. 한도·묶음 없음·재동의·그 밖의 실패는 뒤 작품도 같은 이유로 실패하므로 그 자리에서
 * 멈춘다.
 */
export async function addWorksInOrder<T>(works: readonly T[], put: (work: T) => Promise<void>): Promise<AddWorksResult> {
  let added = 0;
  let gone = 0;
  for (const work of works) {
    try {
      await put(work);
      added += 1;
    } catch (error) {
      const notice = toWorkBundleActionError(error, "addItem");
      if (notice?.kind === "workGone") {
        gone += 1;
        continue;
      }
      return { added, gone, stoppedBy: toStopReason(notice), stopError: error };
    }
  }
  return { added, gone, stoppedBy: undefined, stopError: undefined };
}

function toStopReason(notice: WorkBundleActionError | null): NonNullable<AddWorksResult["stoppedBy"]> {
  if (notice === null) return "reconsent";
  if (notice.kind === "itemLimit" || notice.kind === "bundleGone") return notice.kind;
  return "failed";
}

export type AddWorksDescription = { tone: "success" | "error"; message: string };

/** 결과를 한 문장으로. 재동의로 멈췄으면 재동의 모달이 대신 말하므로 `null` 이다. */
export function describeAddWorksResult(result: AddWorksResult): AddWorksDescription | null {
  const goneNote = result.gone > 0 ? ` ${result.gone}개는 지워졌거나 넣을 수 없는 작품이라 건너뛰었어요.` : "";
  switch (result.stoppedBy) {
    case undefined:
      return result.added > 0
        ? { tone: "success", message: `${result.added}개를 넣었어요.${goneNote}` }
        : { tone: "error", message: `넣은 작품이 없어요.${goneNote}` };
    case "reconsent":
      return null;
    case "bundleGone":
      return { tone: "error", message: "이 묶음을 찾을 수 없어요. 다른 곳에서 지웠을 수 있어요." };
    case "itemLimit":
      return {
        tone: "error",
        message: `${stoppedPrefix(result.added)}한 묶음에는 작품을 ${WORK_BUNDLE_MAX_ITEMS}개까지 넣을 수 있어요.${goneNote}`,
      };
    case "failed":
      return { tone: "error", message: `${stoppedPrefix(result.added)}잠시 후 다시 시도해 주세요.${goneNote}` };
  }
}

function stoppedPrefix(added: number): string {
  return added > 0 ? `${added}개를 넣고 멈췄어요. ` : "넣지 못했어요. ";
}
