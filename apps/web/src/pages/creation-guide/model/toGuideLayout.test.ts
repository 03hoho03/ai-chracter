import { describe, expect, it } from "vitest";

import { parseManuscript } from "./parseManuscript";
import { toGuideLayout } from "./toGuideLayout";

const FENCE = "````";

function layoutOf(markdown: string) {
  return toGuideLayout(parseManuscript(markdown).segments);
}

describe("toGuideLayout", () => {
  it("puts prose before the first heading in the lead", () => {
    const layout = layoutOf("들어가는 글\n## 설정 {#setting}\n설정 글");
    expect(layout.lead).toEqual([{ kind: "markdown", source: "들어가는 글" }]);
    expect(layout.sections).toEqual([
      { id: "setting", title: "설정", blocks: [{ kind: "markdown", source: "설정 글" }] },
    ]);
  });

  it("merges consecutive chat and chat-user blocks into one conversation", () => {
    const layout = layoutOf(
      [`${FENCE}chat free`, "왔어?", FENCE, `${FENCE}chat-user free`, "응", FENCE, `${FENCE}chat free`, "앉아", FENCE].join(
        "\n",
      ),
    );
    expect(layout.lead).toEqual([
      {
        kind: "conversation",
        messages: [
          { role: "character", body: "왔어?" },
          { role: "user", body: "응" },
          { role: "character", body: "앉아" },
        ],
      },
    ]);
  });

  it("starts a new conversation after prose or a field block", () => {
    const layout = layoutOf(
      [
        `${FENCE}chat free`,
        "하나",
        FENCE,
        "사이 글",
        `${FENCE}chat free`,
        "둘",
        FENCE,
        `${FENCE}field free`,
        "*입력*",
        FENCE,
        `${FENCE}chat free`,
        "셋",
        FENCE,
      ].join("\n"),
    );
    expect(layout.lead.map((block) => block.kind)).toEqual([
      "conversation",
      "markdown",
      "conversation",
      "field",
      "conversation",
    ]);
  });

  it("does not merge a conversation across a heading", () => {
    const layout = layoutOf([`${FENCE}chat free`, "앞", FENCE, "## 절 {#next}", `${FENCE}chat free`, "뒤", FENCE].join("\n"));
    expect(layout.lead).toHaveLength(1);
    expect(layout.sections[0]?.blocks).toEqual([{ kind: "conversation", messages: [{ role: "character", body: "뒤" }] }]);
  });
});
