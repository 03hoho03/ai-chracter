import { describe, expect, it } from "vitest";

import {
  attachSceneToMessages,
  describeSceneChange,
  expandStoryScene,
  hasSceneText,
  selectCurrentScene,
  takePendingScene,
  type SceneMessage,
} from "./storyScene";

const INITIAL = { place: "폐광 입구", time: "해 질 녘" };

function user(id: string): SceneMessage {
  return { id, role: "user" };
}

function assistant(id: string, scene?: SceneMessage["scene"]): SceneMessage {
  return { id, role: "assistant", scene };
}

describe("selectCurrentScene", () => {
  it("AI 메시지가 없으면 첫 장면이다", () => {
    expect(selectCurrentScene([], INITIAL)).toEqual(INITIAL);
  });

  it("마지막 AI 메시지에 저장된 장면을 따른다", () => {
    const messages = [assistant("o"), user("u1"), assistant("a1", { place: "갱도", time: undefined })];
    expect(selectCurrentScene(messages, INITIAL)).toEqual({ place: "갱도", time: undefined });
  });

  it("오프닝(앞에 사용자 메시지가 없는 AI 메시지)만 남으면 첫 장면이다 — 오프닝에는 장면이 저장되지 않는다", () => {
    expect(selectCurrentScene([assistant("o")], INITIAL)).toEqual(INITIAL);
  });

  it("장면이 비어 있는 오프닝이 아닌 응답은 첫 장면으로 떨어지지 않고 비운다(헤더를 켜기 전 응답)", () => {
    const messages = [assistant("o"), user("u1"), assistant("a1")];
    expect(selectCurrentScene(messages, INITIAL)).toBeUndefined();
  });

  it("앞의 사용자 메시지만 지워져 오프닝처럼 보여도 저장된 장면을 따른다", () => {
    expect(selectCurrentScene([assistant("a1", { place: "갱도", time: "새벽" })], INITIAL)).toEqual({
      place: "갱도",
      time: "새벽",
    });
  });

  it("앞 메시지를 아직 덜 받은 방이면 장면 없는 첫 AI 메시지를 오프닝으로 보지 않는다", () => {
    expect(selectCurrentScene([assistant("a9")], INITIAL, { hasMoreMessagesBefore: true })).toBeUndefined();
  });

  it("마지막 사용자 메시지 뒤에 아직 답이 없으면 그 앞 AI 응답의 장면이다(보내는 중)", () => {
    const messages = [assistant("o"), user("u1"), assistant("a1", { place: "갱도", time: "새벽" }), user("u2")];
    expect(selectCurrentScene(messages, INITIAL)).toEqual({ place: "갱도", time: "새벽" });
  });
});

describe("attachSceneToMessages", () => {
  it("해당 id 의 메시지에 장면을 붙인다", () => {
    const messages = [assistant("o"), user("u1"), assistant("a1")];
    const next = attachSceneToMessages(messages, "a1", { place: "갱도", time: "새벽" });
    expect(next?.at(-1)).toEqual({ id: "a1", role: "assistant", scene: { place: "갱도", time: "새벽" } });
  });

  it("그 메시지가 아직 없으면 undefined 를 돌려준다(장면 이벤트가 응답 확정보다 먼저 왔다)", () => {
    expect(attachSceneToMessages([assistant("o")], "a1", { place: "갱도", time: undefined })).toBeUndefined();
  });
});

describe("takePendingScene", () => {
  it("먼저 온 장면을 같은 id 의 확정 응답에 붙인다", () => {
    const pending = { messageId: "a1", scene: { place: "갱도", time: "새벽" } };
    expect(takePendingScene({ id: "a1", role: "assistant" as const }, pending)).toEqual({
      id: "a1",
      role: "assistant",
      scene: { place: "갱도", time: "새벽" },
    });
  });

  it("확정 응답이 이미 장면을 실었거나 id 가 다르면 그대로 둔다", () => {
    const pending = { messageId: "a1", scene: { place: "갱도", time: "새벽" } };
    const carried = { id: "a1", role: "assistant" as const, scene: { place: "광장", time: undefined } };
    expect(takePendingScene(carried, pending)).toBe(carried);
    const other = { id: "a2", role: "assistant" as const };
    expect(takePendingScene(other, pending)).toBe(other);
    expect(takePendingScene(other, undefined)).toBe(other);
  });
});

describe("hasSceneText", () => {
  it("장소나 시간 하나라도 있어야 장면 줄을 그린다", () => {
    expect(hasSceneText(undefined)).toBe(false);
    expect(hasSceneText({ place: undefined, time: undefined })).toBe(false);
    expect(hasSceneText({ place: "갱도", time: undefined })).toBe(true);
    expect(hasSceneText({ place: undefined, time: "새벽" })).toBe(true);
  });
});

describe("describeSceneChange", () => {
  it("바뀐 칸마다 한 문장 — 장소 다음 시간", () => {
    expect(describeSceneChange({ place: "입구", time: "밤" }, { place: "갱도", time: "새벽" })).toEqual([
      "장소 바뀜: 갱도",
      "시간 바뀜: 새벽",
    ]);
  });

  it("그대로이거나 비게 된 칸은 읽지 않는다", () => {
    expect(describeSceneChange({ place: "갱도", time: "밤" }, { place: "갱도", time: undefined })).toEqual([]);
    expect(describeSceneChange(undefined, undefined)).toEqual([]);
  });

  it("장면이 처음 생기면 생긴 칸을 읽는다", () => {
    expect(describeSceneChange(undefined, { place: undefined, time: "새벽" })).toEqual(["시간 바뀜: 새벽"]);
  });
});

describe("expandStoryScene", () => {
  it("장소·시간 글을 같은 함수로 바꾼다", () => {
    expect(expandStoryScene({ place: "{{user}}의 방", time: undefined }, (text) => text.replace("{{user}}", "민지"))).toEqual({
      place: "민지의 방",
      time: undefined,
    });
    expect(expandStoryScene(undefined, (text) => text)).toBeUndefined();
  });
});
