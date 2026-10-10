import { describe, expect, it } from "vitest";

import { previewEmptyHint } from "./previewEmptyHint";

describe("previewEmptyHint", () => {
  it.each([
    ["메시지가 없다", []],
    ["인트로가 빈 첫 메시지 하나뿐이다", [{ content: "" }]],
    ["첫 메시지가 공백뿐이다", [{ content: " \n\u3000" }]],
  ])("%s면 안내를 낸다", (_name, messages) => {
    expect(previewEmptyHint("character", messages)).toContain("인트로를 쓰면");
  });

  it.each([
    ["보이는 첫 메시지가 있다", [{ content: "또 늦은 시간에 오셨네요." }]],
    ["빈 첫 메시지 뒤에 보낸 메시지가 있다", [{ content: "" }, { content: "안녕" }]],
  ])("%s면 안내하지 않는다", (_name, messages) => {
    expect(previewEmptyHint("character", messages)).toBeUndefined();
  });

  it("스토리는 첫 시작설정의 시작상황을 말한다", () => {
    expect(previewEmptyHint("story", [])).toContain("첫 번째 시작설정의 시작상황");
    expect(previewEmptyHint("character", [])).not.toContain("시작설정");
  });
});
