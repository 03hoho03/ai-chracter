import { describe, expect, it } from "vitest";

import type { MediaBookValues } from "@/features/build-story";

import { resolveSelectedPosition } from "./useMediaBookSelection";

const DOHEE = "00000000-0000-4000-8000-000000000001";
const YUNA = "00000000-0000-4000-8000-000000000002";
const READING = "00000000-0000-4000-8000-000000000011";
const HEART = "00000000-0000-4000-8000-000000000012";

const BOOK: MediaBookValues = {
  people: [
    { id: DOHEE, name: "도희" },
    { id: YUNA, name: "유나" },
  ],
  scenes: [
    { id: READING, name: "리딩" },
    { id: HEART, name: "진심" },
  ],
  cells: [],
};

describe("resolveSelectedPosition", () => {
  it("keeps the picked cell while both its person and scene exist", () => {
    const selected = { personId: YUNA, sceneId: HEART };
    expect(resolveSelectedPosition(BOOK, selected)).toBe(selected);
  });

  it("treats the detail as closed once the picked cell's person is deleted", () => {
    const withoutYuna = { ...BOOK, people: BOOK.people.filter((person) => person.id !== YUNA) };
    expect(resolveSelectedPosition(withoutYuna, { personId: YUNA, sceneId: HEART })).toBeUndefined();
  });

  it("treats the detail as closed once the picked cell's scene is deleted", () => {
    const withoutHeart = { ...BOOK, scenes: BOOK.scenes.filter((scene) => scene.id !== HEART) };
    expect(resolveSelectedPosition(withoutHeart, { personId: YUNA, sceneId: HEART })).toBeUndefined();
  });

  it("returns nothing when no cell has been picked", () => {
    expect(resolveSelectedPosition(BOOK, undefined)).toBeUndefined();
  });
});
