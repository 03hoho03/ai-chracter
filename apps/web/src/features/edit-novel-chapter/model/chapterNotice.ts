/** 장 머리 아래에 남겨 두는 결과 문장. `error` 는 경고 상자, `info` 는 진행 줄에 남는 문장이다. */
export type ChapterNotice = { tone: "error" | "info"; message: string };

/** 결과 문장을 바꾸는 일. 이 장의 본문을 바꾸거나 바꾸려는 동작(직접 고치기·저장·되돌리기·적용·버리기·AI 수정)은
 * 시작할 때 `started` 를 보내 이전 문장을 지운다 — 남겨 두면 되돌린 뒤에도 "적용했어요"가, 다른 동작 뒤에도 지난
 * 거절 문장이 보인다. */
export type ChapterNoticeEvent =
  | { type: "started" }
  | { type: "manualSaved"; chapterOrdinal: number }
  | { type: "manualUnchanged"; chapterOrdinal: number }
  | { type: "manualCancelled"; chapterOrdinal: number }
  | { type: "applied"; chapterOrdinal: number }
  | { type: "dismissed"; chapterOrdinal: number }
  | { type: "restored"; chapterOrdinal: number; revisionNo: number }
  | { type: "rejected"; message: string };

/** 일 하나가 남기는 문장. 문장은 언제나 마지막 일의 것으로 통째로 바뀐다(앞 문장에 덧붙이지 않는다). 이 문장은
 * 소설 하나에 하나라 장을 옮겨도 남는다 — 다른 장 머리에서 읽혀도 맞도록 결과 문장은 모두 장 번호를 말한다. */
export function toChapterNotice(event: ChapterNoticeEvent): ChapterNotice | undefined {
  switch (event.type) {
    case "started":
      return undefined;
    case "manualSaved":
      return { tone: "info", message: `${event.chapterOrdinal}화를 고쳐 저장했어요. 이전 글은 판 이력에 남아요.` };
    case "manualUnchanged":
      return { tone: "info", message: `${event.chapterOrdinal}화는 바뀐 내용이 없어 그대로 두었어요.` };
    case "manualCancelled":
      return { tone: "info", message: `${event.chapterOrdinal}화 직접 고치기를 그만뒀어요.` };
    case "applied":
      return { tone: "info", message: `${event.chapterOrdinal}화에 수정안을 적용했어요. 이전 글은 판 이력에 남아요.` };
    case "dismissed":
      return { tone: "info", message: `${event.chapterOrdinal}화 수정안을 버렸어요.` };
    case "restored":
      return {
        tone: "info",
        message: `${event.chapterOrdinal}화를 ${event.revisionNo}판으로 되돌렸어요. 되돌리기 전 글도 판 이력에 남아요.`,
      };
    case "rejected":
      return { tone: "error", message: event.message };
  }
}
