import { describe, expect, it } from "vitest";

import { toNovelRightsView, type NovelRightsInput, type SourceRead } from "./novelRights";

const LOCKED_AT = "2026-10-20T03:00:00Z";
const ROOM_ID = "00000000-0000-4000-8000-0000000000aa";

function input(patch: Partial<NovelRightsInput>): NovelRightsInput {
  return {
    novel: {
      chatRoomId: ROOM_ID,
      writingLockedAt: null,
      writingLockPermission: null,
      serialLockedAt: null,
      serialLockPermission: null,
    },
    source: { kind: "loaded", novelPermission: "public", isOwner: false, sourceAvailable: true },
    policyV2Enabled: true,
    ...patch,
  };
}

function novel(patch: Partial<NovelRightsInput["novel"]>): NovelRightsInput["novel"] {
  return { ...input({}).novel, ...patch };
}

describe("toNovelRightsView — 출처", () => {
  it.each<[string, SourceRead, "own" | "derived" | undefined]>([
    ["내 작품이 원작이면 공식", { kind: "loaded", novelPermission: "forbidden", isOwner: true, sourceAvailable: true }, "own"],
    ["남의 작품이 원작이면 파생", { kind: "loaded", novelPermission: "public", isOwner: false, sourceAvailable: true }, "derived"],
    // 원작을 아직 못 읽었거나 읽을 수 없으면 어느 쪽인지 지어내지 않는다.
    ["원작을 읽는 중이면 모름", { kind: "loading" }, undefined],
    ["원작을 읽지 못했으면 모름", { kind: "unavailable" }, undefined],
  ])("%s", (_, source, expected) => {
    expect(toNovelRightsView(input({ source })).origin).toBe(expected);
  });

  it("원래 대화방이 있으면 그 방, 지워졌으면 null 이다", () => {
    expect(toNovelRightsView(input({})).chatRoomId).toBe(ROOM_ID);
    expect(toNovelRightsView(input({ novel: novel({ chatRoomId: null }) })).chatRoomId).toBeNull();
  });
});

describe("toNovelRightsView — 지금 허용 범위", () => {
  it.each([
    ["forbidden", "허용 안 함"],
    ["private", "나만 보는 소설"],
    ["public", "공개 소설까지"],
  ] as const)("남의 작품은 원작자가 지금 고른 단계(%s)를 그 라벨로 보인다", (permission, label) => {
    const view = toNovelRightsView(input({ source: { kind: "loaded", novelPermission: permission, isOwner: false, sourceAvailable: true } }));
    expect(view.allowance).toEqual({ kind: "permission", permission, label });
  });

  // 운영 조치로 내려간 원작은 새로 소설을 만들 수도 공개할 수도 없다 — 원작자가 고른 단계를 "지금 허용"으로 보이면 거짓이다.
  it.each([false, true])("원작이 내려갔으면 단계 대신 볼 수 없다고 말한다(내 작품 %s)", (isOwner) => {
    const view = toNovelRightsView(
      input({ source: { kind: "loaded", novelPermission: "public", isOwner, sourceAvailable: false } }),
    );
    expect(view.allowance).toEqual({ kind: "sourceDown" });
  });

  // 허락은 남에게 거는 조건이라 원작자 본인에게는 단계가 아무 뜻이 없다 — 단계를 보이면 "내가 막아 둬서 못 쓰나"로 읽힌다.
  it("내 작품은 단계 대신 허락이 필요 없다고 말한다", () => {
    const view = toNovelRightsView(input({ source: { kind: "loaded", novelPermission: "forbidden", isOwner: true, sourceAvailable: true } }));
    expect(view.allowance).toEqual({ kind: "own" });
  });

  it.each<[SourceRead, string]>([
    [{ kind: "loading" }, "loading"],
    [{ kind: "unavailable" }, "unavailable"],
  ])("원작을 못 읽었으면 단계를 지어내지 않는다 (%o)", (source, kind) => {
    expect(toNovelRightsView(input({ source })).allowance).toEqual({ kind });
  });
});

describe("toNovelRightsView — 집필권", () => {
  it("잠기기 전이면 첫 화 저장 때 생긴다고 말한다", () => {
    expect(toNovelRightsView(input({})).writing).toEqual({ kind: "none", when: "첫 화를 저장하면 생겨요." });
  });

  it("잠겼으면 시각·그때 허락·효력을 싣는다", () => {
    const view = toNovelRightsView(
      input({ novel: novel({ writingLockedAt: LOCKED_AT, writingLockPermission: "private" }) }),
    );
    expect(view.writing).toEqual({
      kind: "locked",
      lockedAt: LOCKED_AT,
      heldPermission: "그때 허락 · 나만 보는 소설",
      effect: "원작자가 허락을 거둬도 이 소설은 이어 쓸 수 있어요.",
    });
  });

  // 허락 사본이 비어 있는 잠금은 뒤늦게 채웠거나 그 순간 원작 행이 없던 것이다 — "허용 안 함"으로 읽으면 거짓이다.
  it("허락 사본이 없으면 알 수 없다고 말한다", () => {
    const view = toNovelRightsView(input({ novel: novel({ writingLockedAt: LOCKED_AT, writingLockPermission: null }) }));
    expect(view.writing).toMatchObject({ kind: "locked", heldPermission: "그때 허락은 알 수 없어요" });
  });

  it.each<[string, SourceRead]>([
    ["내 작품", { kind: "loaded", novelPermission: "forbidden", isOwner: true, sourceAvailable: true }],
    ["원작을 모름", { kind: "unavailable" }],
  ])("%s이면 효력 문장을 붙이지 않는다", (_, source) => {
    const view = toNovelRightsView(
      input({ source, novel: novel({ writingLockedAt: LOCKED_AT, writingLockPermission: "public" }) }),
    );
    expect(view.writing).toMatchObject({ kind: "locked", effect: undefined });
  });

  // 집필권의 효력은 노벨 정책 스위치와 무관하다 — 스위치가 꺼져도 문장은 참이다.
  it("정책 스위치가 꺼져도 집필권 효력 문장은 남는다", () => {
    const view = toNovelRightsView(
      input({ policyV2Enabled: false, novel: novel({ writingLockedAt: LOCKED_AT, writingLockPermission: "public" }) }),
    );
    expect(view.writing).toMatchObject({ effect: "원작자가 허락을 거둬도 이 소설은 이어 쓸 수 있어요." });
  });
});

// 방이 지워진 소설은 이미 만든 화를 읽고 고칠 수만 있고 새 화를 못 만든다 — "이어 쓸 수 있어요"·"첫 화를 저장하면"은 거짓이다.
describe("toNovelRightsView — 방이 지워진 소설", () => {
  it("잠겼어도 이어 쓰기 효력 문장을 붙이지 않는다", () => {
    const view = toNovelRightsView(
      input({ novel: novel({ chatRoomId: null, writingLockedAt: LOCKED_AT, writingLockPermission: "public" }) }),
    );
    expect(view.writing).toMatchObject({ kind: "locked", effect: undefined });
  });

  it("잠기기 전이면 새 화를 만들 수 없다고 말한다", () => {
    expect(toNovelRightsView(input({ novel: novel({ chatRoomId: null }) })).writing).toEqual({
      kind: "none",
      when: "원래 대화가 지워져 새 화를 만들 수 없어요.",
    });
  });
});

describe("toNovelRightsView — 연재권", () => {
  it("잠기기 전이면 노벨에 처음 공개될 때 생긴다고 말한다", () => {
    expect(toNovelRightsView(input({})).serial).toEqual({ kind: "none", when: "노벨에 처음 공개되면 생겨요." });
  });

  it("스위치가 켜졌고 파생이면 이어 공개 효력을 말한다", () => {
    const view = toNovelRightsView(
      input({ novel: novel({ serialLockedAt: LOCKED_AT, serialLockPermission: "public" }) }),
    );
    expect(view.serial).toEqual({
      kind: "locked",
      lockedAt: LOCKED_AT,
      heldPermission: "그때 허락 · 공개 소설까지",
      effect: "원작자가 허락을 거둬도 다음 화를 이어 공개할 수 있어요.",
    });
  });

  // 연재권 잠금은 스위치와 무관하게 찍히지만 효력은 스위치가 켜졌을 때뿐이다 — 끈 뒤에 효력 문장을 보이면 거짓이 된다.
  it.each([false, undefined])("스위치가 꺼졌거나 모르면(%s) 효력 문장을 빼고 잠금 사실만 남긴다", (policyV2Enabled) => {
    const view = toNovelRightsView(
      input({ policyV2Enabled, novel: novel({ serialLockedAt: LOCKED_AT, serialLockPermission: "public" }) }),
    );
    expect(view.serial).toEqual({
      kind: "locked",
      lockedAt: LOCKED_AT,
      heldPermission: "그때 허락 · 공개 소설까지",
      effect: undefined,
    });
  });

  it("내 작품이면 스위치가 켜져도 효력 문장이 없다", () => {
    const view = toNovelRightsView(
      input({
        source: { kind: "loaded", novelPermission: "forbidden", isOwner: true, sourceAvailable: true },
        novel: novel({ serialLockedAt: LOCKED_AT, serialLockPermission: "forbidden" }),
      }),
    );
    expect(view.serial).toMatchObject({ kind: "locked", effect: undefined });
  });

  // 내려간 원작에는 잠금이 있어도 새로 공개할 수 없다 — 바로 위 "운영 조치로 내려가 있어요" 옆에 이어 공개 문장을 두면 거짓으로 읽힌다.
  it("원작이 내려갔으면 효력 문장을 붙이지 않는다", () => {
    const view = toNovelRightsView(
      input({
        source: { kind: "loaded", novelPermission: "public", isOwner: false, sourceAvailable: false },
        novel: novel({ serialLockedAt: LOCKED_AT, serialLockPermission: "public" }),
      }),
    );
    expect(view.serial).toMatchObject({ kind: "locked", effect: undefined });
  });

  it("허락 사본이 없으면 알 수 없다고 말한다", () => {
    const view = toNovelRightsView(input({ novel: novel({ serialLockedAt: LOCKED_AT, serialLockPermission: null }) }));
    expect(view.serial).toMatchObject({ kind: "locked", heldPermission: "그때 허락은 알 수 없어요" });
  });
});
