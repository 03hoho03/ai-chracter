import { describe, expect, it } from "vitest";

import { deleteCopy } from "./deleteCopy";

const RUN_ID = "cnVucy9hL2NoYXQuanNvbmw";
const PATH = "2026-11-05/lighthouse/chat.jsonl";

describe("deleteCopy", () => {
  it("판이 여럿이면 제목과 버튼에 판 N개 모두가 들어간다 — 최신 판 하나만 지우는 것이 아님을 누르기 전에 본다", () => {
    const copy = deleteCopy({ versionCount: 3, runId: RUN_ID, storyName: "지어낸 이야기", path: PATH });

    expect(copy.title).toBe("런을 지운다 — 판 3개 모두");
    expect(copy.confirmLabel).toBe("판 3개 모두 지우기");
  });

  it("판이 하나면 판 1개로 쓴다 — 모두를 붙이지 않는다", () => {
    const copy = deleteCopy({ versionCount: 1, runId: RUN_ID, storyName: "지어낸 이야기", path: PATH });

    expect(copy.title).toBe("런을 지운다 — 판 1개");
    expect(copy.confirmLabel).toBe("판 1개 지우기");
  });

  it("판 2개도 여럿이다 — 제목·버튼·잇는 문장에 판 2개 모두가 들어간다", () => {
    const copy = deleteCopy({ versionCount: 2, runId: RUN_ID, storyName: "지어낸 이야기", path: PATH });

    expect(copy.title).toBe("런을 지운다 — 판 2개 모두");
    expect(copy.confirmLabel).toBe("판 2개 모두 지우기");
    expect(copy.scope).toBe("판 2개를 모두 지운다. 최신 판 하나만 지우는 것이 아니다.");
  });

  it("판이 여럿이면 런 뒤에 잇는 문장이 모두 지운다고 경고하고, 하나면 경고하지 않는다", () => {
    const many = deleteCopy({ versionCount: 3, runId: RUN_ID, storyName: "지어낸 이야기", path: PATH });
    const one = deleteCopy({ versionCount: 1, runId: RUN_ID, storyName: "지어낸 이야기", path: PATH });

    expect(many.scope).toBe("판 3개를 모두 지운다. 최신 판 하나만 지우는 것이 아니다.");
    expect(one.scope).toBe("판 1개를 지운다.");
    expect(one.scope).not.toContain("최신 판 하나만");
  });

  it("이야기 이름이 있으면 그 이름으로 런을 가리킨다", () => {
    expect(deleteCopy({ versionCount: 2, runId: RUN_ID, storyName: "지어낸 이야기", path: PATH }).subject).toEqual({
      kind: "story",
      name: "지어낸 이야기",
    });
  });

  it("이야기 이름이 없으면 런 경로를 쓴다 — 화면은 경로를 고정폭으로 그린다", () => {
    expect(deleteCopy({ versionCount: 2, runId: RUN_ID, storyName: null, path: PATH }).subject).toEqual({
      kind: "path",
      path: PATH,
    });
    expect(deleteCopy({ versionCount: 2, runId: RUN_ID, storyName: undefined, path: PATH }).subject).toEqual({
      kind: "path",
      path: PATH,
    });
  });

  it("이야기 이름·경로 둘 다 없으면 런 id 로 가리킨다 — 목록 칸 꼴이 틀려 읽지 못하는 런도 지울 수 있다", () => {
    expect(deleteCopy({ versionCount: 2, runId: RUN_ID }).subject).toEqual({ kind: "runId", runId: RUN_ID });
    expect(deleteCopy({ versionCount: 2, runId: RUN_ID, storyName: null, path: undefined }).subject).toEqual({
      kind: "runId",
      runId: RUN_ID,
    });
  });
});
