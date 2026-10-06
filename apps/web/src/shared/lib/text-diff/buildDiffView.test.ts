import { describe, expect, it, vi } from "vitest";

import { buildDiffView, createDiffRunners, type DiffBlock, type DiffRunners, type DiffView } from "./buildDiffView";

function blocksOf(view: DiffView): DiffBlock[] {
  if (view.status !== "compared") throw new Error(`expected a comparison, got ${view.status}`);
  return view.blocks;
}

function changedTexts(block: DiffBlock | undefined, kind: "added" | "removed"): string[] {
  if (block?.kind !== "changed") return [];
  return block.segments.filter((segment) => segment.kind === kind).map((segment) => segment.text.trim());
}

/** 같은 씨앗이면 언제나 같은 글을 만드는 한국어 문장 생성기. 음절 집합을 달리하면 겹치는 단어가 없는 글이 된다. */
function koreanProse(seed: number, syllables: string, targetLength: number): string {
  let state = seed;
  const next = () => {
    state = (state * 1103515245 + 12345) % 2147483648;
    return state;
  };
  const word = () =>
    Array.from({ length: 2 + (next() % 3) }, () => syllables[next() % syllables.length]).join("");
  const paragraphs: string[] = [];
  let length = 0;
  while (length < targetLength) {
    const sentences = Array.from({ length: 4 }, () => `${Array.from({ length: 6 }, word).join(" ")}다.`);
    const paragraph = sentences.join(" ");
    paragraphs.push(paragraph);
    length += paragraph.length + 2;
  }
  return paragraphs.join("\n\n");
}

const stub = (words: ReturnType<DiffRunners["words"]>, sentences: ReturnType<DiffRunners["sentences"]>) => ({
  words: vi.fn<DiffRunners["words"]>(() => words),
  sentences: vi.fn<DiffRunners["sentences"]>(() => sentences),
});

describe("buildDiffView", () => {
  it("expands only the changed paragraph and folds the unchanged ones around it", () => {
    const before = "첫 문단은 그대로다.\n\n둘째 문단도 그대로다.\n\n그는 문을 열었다.\n\n넷째 문단도 그대로다.";
    const after = "첫 문단은 그대로다.\n\n둘째 문단도 그대로다.\n\n그는 창문을 열었다.\n\n넷째 문단도 그대로다.";
    const view = buildDiffView(before, after);
    expect(view).toMatchObject({ status: "compared", granularity: "word", changedParagraphCount: 1 });

    const blocks = blocksOf(view);
    expect(blocks.map((block) => block.kind)).toEqual(["unchanged", "changed", "unchanged"]);
    expect(blocks[0]).toEqual({ kind: "unchanged", paragraphs: ["첫 문단은 그대로다.", "둘째 문단도 그대로다."] });
    expect(changedTexts(blocks[1], "removed")).toEqual(["문을"]);
    expect(changedTexts(blocks[1], "added")).toEqual(["창문을"]);
    expect(blocks[2]).toEqual({ kind: "unchanged", paragraphs: ["넷째 문단도 그대로다."] });
  });

  it("reports no changed paragraph for identical text", () => {
    const text = "하나.\n\n둘.";
    const view = buildDiffView(text, text);
    expect(view).toMatchObject({ status: "compared", changedParagraphCount: 0 });
    expect(blocksOf(view)).toEqual([{ kind: "unchanged", paragraphs: ["하나.", "둘."] }]);
  });

  it("marks only the inserted paragraph as changed, not the untouched paragraph after it", () => {
    const view = buildDiffView("앞 문단.\n\n뒤 문단.", "앞 문단.\n\n새로 넣은 문단.\n\n뒤 문단.");
    const blocks = blocksOf(view);
    expect(blocks.map((block) => block.kind)).toEqual(["unchanged", "changed", "unchanged"]);
    expect(changedTexts(blocks[1], "added").join(" ")).toContain("새로 넣은 문단");
    expect(blocks[2]).toEqual({ kind: "unchanged", paragraphs: ["뒤 문단."] });
  });

  it("does not run the sentence diff when the word diff finishes", () => {
    const runners = stub([{ value: "같다.", added: false, removed: false, count: 1 }], undefined);
    expect(buildDiffView("같다.", "같다.", runners)).toMatchObject({ status: "compared", granularity: "word" });
    expect(runners.sentences).not.toHaveBeenCalled();
  });

  it("falls back to sentences when the word diff gives up", () => {
    const runners = stub(undefined, [
      { value: "옛 문장.", added: false, removed: true, count: 1 },
      { value: "새 문장.", added: true, removed: false, count: 1 },
    ]);
    const view = buildDiffView("옛 문장.", "새 문장.", runners);
    expect(view).toMatchObject({ status: "compared", granularity: "sentence", changedParagraphCount: 1 });
    expect(runners.words).toHaveBeenCalledWith("옛 문장.", "새 문장.");
  });

  it("reports the difference as too large when both diffs give up", () => {
    expect(buildDiffView("가", "나", stub(undefined, undefined))).toEqual({ status: "tooLarge" });
  });

  it("falls back to sentences with the real diff when words time out on two fully different 5,000-character Korean texts", () => {
    const before = koreanProse(1, "가나다라마바사아자차카타파하", 5000);
    const after = koreanProse(2, "강낭당랑망방상앙장창캉탕팡항", 5000);
    expect(before.length).toBeGreaterThanOrEqual(5000);
    expect(after.length).toBeGreaterThanOrEqual(5000);

    // 단어 단위 비교는 이 입력에서 수백 ms 가 걸린다. 기본 상한(200ms)과의 차이가 기계 속도에 따라 줄어들 수 있어,
    // 단어 쪽 상한만 1ms 로 줄여 시간 초과 갈래를 확실히 탄다. 문장 쪽은 기본 상한 그대로 끝나야 한다.
    const view = buildDiffView(before, after, createDiffRunners(1));

    expect(view).toMatchObject({ status: "compared", granularity: "sentence" });
    const blocks = blocksOf(view);
    expect(blocks.every((block) => block.kind === "changed")).toBe(true);
  });
});
