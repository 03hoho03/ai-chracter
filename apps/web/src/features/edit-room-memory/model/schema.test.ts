import { createFormControl } from "react-hook-form";
import { describe, expect, it } from "vitest";

import { countMemoryChars, createMemoryFormSchema, memoryFormOptions } from "./schema";

const limits = { noteMaxLength: 1000, summaryMaxLength: 1500 };
const schema = createMemoryFormSchema(limits);

describe("createMemoryFormSchema", () => {
  // 서버 요청 스키마와 같은 규칙을 FE가 먼저 막는다 — 422 원문을 보이지 않고, 붙여넣기가 조용히 잘리지
  // 않게(입력칸에 maxLength를 두지 않는다).
  it("accepts both fields at their limits after trimming the surrounding whitespace", () => {
    const result = schema.safeParse({ note: `  ${"가".repeat(1000)}\n`, summary: ` ${"나".repeat(1500)} ` });
    expect(result.success).toBe(true);
    expect(result.data).toEqual({ note: "가".repeat(1000), summary: "나".repeat(1500) });
  });

  it("allows saving an empty note and an empty summary", () => {
    expect(schema.safeParse({ note: "   ", summary: "" }).data).toEqual({ note: "", summary: "" });
  });

  it.each([
    ["note", { note: "가".repeat(1001), summary: "" }],
    ["summary", { note: "", summary: "나".repeat(1501) }],
  ])("rejects a %s one character over the limit on that field only", (field, values) => {
    const result = schema.safeParse(values);
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((issue) => issue.path[0])).toEqual([field]);
  });

  it("takes the limits from the server response instead of a local copy", () => {
    const narrow = createMemoryFormSchema({ noteMaxLength: 3, summaryMaxLength: 5 });
    expect(narrow.safeParse({ note: "가나다", summary: "가나다라마" }).success).toBe(true);
    expect(narrow.safeParse({ note: "가나다라", summary: "" }).success).toBe(false);
  });

  // 서버는 코드 포인트로 센다 — 이모지는 JS `.length`로 2지만 서버에서는 1자라, 서버가 받는 입력을 FE가
  // 막으면 안 된다.
  it.each([
    ["note", { note: "😀".repeat(1000), summary: "" }],
    ["summary", { note: "", summary: "😀".repeat(1500) }],
  ])("accepts a %s of emoji exactly at the limit the server also accepts", (_field, values) => {
    expect(schema.safeParse(values).success).toBe(true);
  });

  it("rejects a note of emoji one character over the limit", () => {
    expect(schema.safeParse({ note: "😀".repeat(1001), summary: "" }).success).toBe(false);
  });
});

describe("countMemoryChars", () => {
  it("counts an emoji as one character after trimming the surrounding whitespace", () => {
    expect(countMemoryChars(" 😀가\n")).toBe(2);
  });
});

describe("memoryFormOptions", () => {
  function createForm() {
    const form = createFormControl({ ...memoryFormOptions(schema), defaultValues: { note: "", summary: "" } });
    // `useForm`처럼 폼 상태를 구독한다 — 구독자가 없으면 제출됨(`isSubmitted`)이 폼에 반영되지 않아 제출 뒤
    // 재검증 규칙을 볼 수 없다.
    form.subscribe({ formState: { errors: true }, callback: () => {} });
    const type = async (field: "note" | "summary", value: string) => {
      await form.register(field).onChange({ target: { name: field, value }, type: "change" });
    };
    const save = async () => {
      let saved = false;
      await form.handleSubmit(() => {
        saved = true;
      })();
      return saved;
    };
    return { form, type, save };
  }

  // [저장]은 폼 제출이다. 상한을 넘겨 저장이 막힌 뒤 글자를 지워 상한 아래로 내리면, [저장]을 다시 누르지
  // 않아도 오류와 `aria-invalid`가 곧바로 풀려야 한다.
  it.each([
    ["note", 1000],
    ["summary", 1500],
  ] as const)("clears the %s over-limit error as soon as the text is back within the limit", async (field, limit) => {
    const { form, type, save } = createForm();

    await type(field, "가".repeat(limit + 1));
    expect(await save()).toBe(false);
    expect(form.getFieldState(field).error?.message).toBe(`${limit}자 이내로 적어 주세요`);

    await type(field, "가".repeat(limit));
    expect(form.getFieldState(field).error).toBeUndefined();
  });

  // 저장은 폼 전체를 검증한다 — 고치는 중인 요약이 상한을 넘기면 노트 저장도 막힌다.
  it("blocks saving the note while the summary being edited is over its limit", async () => {
    const { form, type, save } = createForm();

    await type("note", "고양이");
    await type("summary", "나".repeat(1501));
    expect(await save()).toBe(false);
    expect(form.getFieldState("summary").error).toBeDefined();
    expect(form.getFieldState("note").error).toBeUndefined();
  });
});
