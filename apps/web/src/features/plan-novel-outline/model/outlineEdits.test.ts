import { describe, expect, it } from "vitest";

import type { NovelOutlineView } from "@/entities/novel";

import {
  isSameAsView,
  mergeWithNext,
  moveEpisode,
  removeEpisode,
  splitEpisode,
  toBasisLabel,
  toEpisodeDrafts,
  toEpisodeTurns,
  toOutlineProblems,
  toSaveEpisodes,
  toSplitPoints,
  toTurnIndex,
  updateEpisodeText,
  type OutlineEpisodeDraft,
  type OutlineTurn,
} from "./outlineEdits";

// 메시지 차례: u1 a1 | u2 a2 | u3 a3 a3b | u4 | u5 a5 | u6 a6 — 4턴은 응답 없는 말 하나다.
const TURNS: OutlineTurn[] = [
  { key: "u1", number: 1, messageIds: ["u1", "a1"], excerpt: "첫째", hasResponse: true },
  { key: "u2", number: 2, messageIds: ["u2", "a2"], excerpt: "둘째", hasResponse: true },
  { key: "u3", number: 3, messageIds: ["u3", "a3", "a3b"], excerpt: "셋째", hasResponse: true },
  { key: "u4", number: 4, messageIds: ["u4"], excerpt: "넷째", hasResponse: false },
  { key: "u5", number: 5, messageIds: ["u5", "a5"], excerpt: "다섯째", hasResponse: true },
  { key: "u6", number: 6, messageIds: ["u6", "a6"], excerpt: "여섯째", hasResponse: true },
];
const INDEX = toTurnIndex(TURNS);

function range(startMessageId: string, endMessageId: string) {
  return { startMessageId, endMessageId };
}

function draft(localId: string, basis: OutlineEpisodeDraft["basis"], extra: Partial<OutlineEpisodeDraft> = {}): OutlineEpisodeDraft {
  return {
    localId,
    key: localId,
    title: `${localId} 제목`,
    summary: `${localId} 줄거리`,
    goal: `${localId} 목표`,
    basis,
    chapterId: null,
    ...extra,
  };
}

const A = draft("A", [range("u1", "a2")]);
const B = draft("B", [range("u3", "a6")]);

describe("구성안 편집 — 서버 판에서 편집 화로", () => {
  const view = {
    revision: 3,
    source: "generate",
    model: "gemini",
    approvedAt: null,
    createdAt: "2026-10-24T00:00:00Z",
    stale: false,
    episodes: [
      {
        key: "k1",
        title: "첫 화",
        summary: "줄거리",
        goal: "",
        basis: [range("u1", "a2")],
        chapterId: null,
        sceneOutline: "none",
      },
    ],
  } satisfies NovelOutlineView;

  it("서버 키가 화면 열쇠가 된다", () => {
    expect(toEpisodeDrafts(view)).toEqual([
      { localId: "k1", key: "k1", title: "첫 화", summary: "줄거리", goal: "", basis: [range("u1", "a2")], chapterId: null },
    ]);
  });

  it("고치지 않았으면 판과 같고, 글 하나·차례 하나만 바뀌어도 다르다", () => {
    const drafts = toEpisodeDrafts(view);
    expect(isSameAsView(drafts, view)).toBe(true);
    expect(isSameAsView(updateEpisodeText(drafts, "k1", { title: "새 제목", summary: "줄거리", goal: "" }), view)).toBe(false);
    const second: NovelOutlineView["episodes"][number] = {
      key: "k2",
      title: "둘째 화",
      summary: "줄거리",
      goal: "",
      basis: [range("u3", "a3b")],
      chapterId: null,
      sceneOutline: "none",
    };
    const two = { ...view, episodes: [...view.episodes, second] };
    const twoDrafts = toEpisodeDrafts(two);
    expect(isSameAsView(moveEpisode(twoDrafts, "k2", -1), two)).toBe(false);
  });
});

describe("구성안 편집 — 근거 턴", () => {
  it("근거 구간이 덮는 턴을 차례대로 준다", () => {
    expect(toEpisodeTurns(INDEX, B.basis)?.map((turn) => turn.number)).toEqual([3, 4, 5, 6]);
  });

  it("근거 메시지를 지금 대화에서 못 찾으면 턴을 주지 않는다", () => {
    expect(toEpisodeTurns(INDEX, [range("u1", "gone")])).toBeUndefined();
  });

  it("근거 라벨은 이어진 턴을 범위로, 떨어진 구간은 가운뎃점으로 잇는다", () => {
    expect(toBasisLabel(INDEX, A.basis)).toBe("1~2턴");
    expect(toBasisLabel(INDEX, [range("u1", "a1"), range("u3", "a3b")])).toBe("1턴 · 3턴");
    expect(toBasisLabel(INDEX, [range("u1", "gone")])).toBeUndefined();
  });
});

describe("구성안 편집 — 나누기", () => {
  it("응답으로 끝나는 턴 뒤만 나눌 수 있다(응답 없는 말 하나뿐인 턴 뒤는 안 된다)", () => {
    expect(toSplitPoints(INDEX, B.basis)).toEqual([
      { afterTurnNumber: 3, cutMessageId: "a3b" },
      { afterTurnNumber: 5, cutMessageId: "a5" },
    ]);
  });

  it("턴 하나뿐인 화는 나눌 곳이 없다", () => {
    expect(toSplitPoints(INDEX, [range("u2", "a2")])).toEqual([]);
  });

  it("구간 가운데서 자르면 앞 화는 그 턴 응답까지, 뒤 화는 바로 다음 메시지부터다", () => {
    const result = splitEpisode([A, B], "B", "a5", INDEX, "new-1");
    expect(result).toEqual([
      A,
      { ...B, basis: [range("u3", "a5")] },
      { ...B, localId: "new-1", key: null, title: "B 제목 (뒤)", basis: [range("u6", "a6")] },
    ]);
  });

  it("구간 사이에서 자르면 구간을 그대로 나눠 가진다", () => {
    const two = draft("C", [range("u1", "a1"), range("u3", "a3b")]);
    const result = splitEpisode([two], "C", "a1", INDEX, "new-1");
    expect(result?.map((item) => item.basis)).toEqual([[range("u1", "a1")], [range("u3", "a3b")]]);
  });

  it("나눌 수 없는 자리(응답이 아닌 메시지·화 끝)는 거절한다", () => {
    expect(splitEpisode([B], "B", "u4", INDEX, "new-1")).toBeUndefined();
    expect(splitEpisode([B], "B", "a6", INDEX, "new-1")).toBeUndefined();
  });

  it("뒤 화 제목은 상한 안에서 앞 제목을 줄여 표시를 붙인다", () => {
    const long = draft("L", B.basis, { title: "가".repeat(100) });
    const title = splitEpisode([long], "L", "a5", INDEX, "new-1", { titleMaxLength: 100 })?.[1]?.title ?? "";
    expect([...title].length).toBe(100);
    expect(title.endsWith(" (뒤)")).toBe(true);
  });
});

describe("구성안 편집 — 합치기", () => {
  it("다음 화와 합치면 앞 화의 키·제목이 남고 글을 잇고 근거는 대화 차례다", () => {
    expect(mergeWithNext([A, B], "A", INDEX)).toEqual({
      episodes: [
        {
          ...A,
          summary: "A 줄거리\nB 줄거리",
          goal: "A 목표\nB 목표",
          basis: [range("u1", "a2"), range("u3", "a6")],
        },
      ],
    });
  });

  it("차례를 바꾼 뒤 합쳐도 근거는 대화 차례로 정렬한다", () => {
    const result = mergeWithNext([B, A], "B", INDEX);
    expect(result).toEqual({
      episodes: [{ ...B, summary: "B 줄거리\nA 줄거리", goal: "B 목표\nA 목표", basis: [range("u1", "a2"), range("u3", "a6")] }],
    });
  });

  it("빈 목표는 잇지 않는다", () => {
    const result = mergeWithNext([{ ...A, goal: "" }, B], "A", INDEX);
    expect("episodes" in result && result.episodes[0]?.goal).toBe("B 목표");
  });

  it("마지막 화·원고가 있는 화·대화를 못 받은 때·근거가 너무 많아지는 때는 합치지 않고 이유를 준다", () => {
    expect(mergeWithNext([A, B], "B", INDEX)).toEqual({ reason: "마지막 화라 합칠 다음 화가 없어요." });
    expect(mergeWithNext([{ ...A, chapterId: "c1" }, B], "A", INDEX)).toEqual({ reason: "원고가 있는 화는 합칠 수 없어요." });
    expect(mergeWithNext([A, { ...B, chapterId: "c2" }], "A", INDEX)).toEqual({ reason: "원고가 있는 화는 합칠 수 없어요." });
    expect(mergeWithNext([A, B], "A", undefined)).toEqual({ reason: "대화를 불러온 뒤 합칠 수 있어요." });
    const many = Array.from({ length: 26 }, () => range("u1", "a1"));
    expect(mergeWithNext([{ ...A, basis: many }, { ...B, basis: many }], "A", INDEX)).toEqual({
      reason: "근거 구간이 많아 합칠 수 없어요.",
    });
  });
});

describe("구성안 편집 — 차례·지우기·글", () => {
  it("위로·아래로 옮기고, 끝에서는 그대로다", () => {
    expect(moveEpisode([A, B], "B", -1)).toEqual([B, A]);
    expect(moveEpisode([A, B], "A", 1)).toEqual([B, A]);
    expect(moveEpisode([A, B], "A", -1)).toEqual([A, B]);
    expect(moveEpisode([A, B], "B", 1)).toEqual([A, B]);
  });

  it("지우기는 그 화만 빼고, 마지막 남은 화는 지우지 않는다", () => {
    expect(removeEpisode([A, B], "A")).toEqual([B]);
    expect(removeEpisode([A], "A")).toEqual([A]);
  });

  it("글 고치기는 그 화만 바꾼다", () => {
    expect(updateEpisodeText([A, B], "B", { title: "새", summary: "새 줄거리", goal: "" })).toEqual([
      A,
      { ...B, title: "새", summary: "새 줄거리", goal: "" },
    ]);
  });
});

describe("구성안 편집 — 저장 몸·문제", () => {
  it("저장 몸은 키를 남기고(나눈 화는 비움) 글의 앞뒤 공백을 걷는다", () => {
    const split = { ...B, localId: "new-1", key: null, title: "  뒤  ", summary: " 내용 ", goal: " " };
    expect(toSaveEpisodes([A, split])).toEqual([
      { key: "A", title: "A 제목", summary: "A 줄거리", goal: "A 목표", basis: [range("u1", "a2")] },
      { key: null, title: "뒤", summary: "내용", goal: "", basis: [range("u3", "a6")] },
    ]);
  });

  it("빈 제목·빈 줄거리·넘친 글·화 수 상한을 화 번호와 함께 짚는다", () => {
    const limits = { titleMaxLength: 100, maxEpisodes: 2 };
    expect(toOutlineProblems([A, B], [3, 4], limits)).toEqual([]);
    expect(
      toOutlineProblems(
        [
          { ...A, title: "  " },
          { ...B, summary: "가".repeat(1001), goal: "나".repeat(301) },
        ],
        [3, 4],
        limits,
      ),
    ).toEqual(["3화 제목을 적어주세요.", "4화 줄거리가 1000자를 넘어요.", "4화 목표가 300자를 넘어요."]);
    expect(toOutlineProblems([A, B, { ...A, localId: "C", key: null }], [3, 4, 5], limits)).toEqual([
      "구성안은 2화까지예요. 화를 합치거나 지워주세요.",
    ]);
  });
});
