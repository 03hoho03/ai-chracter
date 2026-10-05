import { describe, expect, it } from "vitest";

import { formToServer } from "./formToServer";
import { countNotesChars, createNotesFormSchema } from "./schema";
import { serverToForm } from "./serverToForm";

let counter = 0;
const nextId = () => `id-${(counter += 1)}`;

describe("serverToForm", () => {
  it("줄마다 사실 하나로 펴고 빈 줄·앞뒤 공백을 버린다", () => {
    expect(serverToForm("  민수는 고양이를 키운다\n\n \n지하철 2호선  ", nextId).notes.map((note) => note.text)).toEqual([
      "민수는 고양이를 키운다",
      "지하철 2호선",
    ]);
  });

  it("빈 노트는 줄이 없다", () => {
    expect(serverToForm("", nextId).notes).toEqual([]);
  });
});

describe("formToServer", () => {
  it("빈 줄을 버리고 줄바꿈 하나로 잇는다", () => {
    expect(
      formToServer({ notes: [{ text: " 가 " }, { text: "   " }, { text: "나" }] }),
    ).toEqual({ settingNotes: "가\n나" });
  });

  it("서버 값을 폈다가 다시 이으면 같은 글이다", () => {
    const settingNotes = "가\n나\n다";
    expect(formToServer(serverToForm(settingNotes, nextId))).toEqual({ settingNotes });
  });
});

describe("createNotesFormSchema", () => {
  it("서버로 보낼 글 전체가 상한 안이면 통과한다 — 빈 줄은 세지 않는다", () => {
    const schema = createNotesFormSchema(3);
    expect(schema.safeParse({ notes: [{ id: "a", text: "가나" }, { id: "b", text: "   " }] }).success).toBe(true);
  });

  it("줄 사이 줄바꿈까지 세어 상한을 넘으면 노트 칸에 오류를 둔다", () => {
    const schema = createNotesFormSchema(3);
    const result = schema.safeParse({ notes: [{ id: "a", text: "가나" }, { id: "b", text: "다" }] });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.path).toEqual(["notes"]);
  });

  it("글자는 코드 포인트로 센다", () => {
    expect(countNotesChars(" 😀가 ")).toBe(2);
  });
});
