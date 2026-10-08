import { assertNever } from "@/shared/lib/assertNever";

import type { MockupKind } from "../config/storyFieldMockups";

/**
 * 원고 목업 값 본문을 칸 모양에 맞게 읽은 결과. 렌더러와 원고 검사 테스트가 같이 쓴다 — 본문이 칸 모양과 맞지 않으면
 * 화면에 엉뚱한 글자가 찍히는 대신 오류를 던진다.
 *
 * 글 칸은 본문 그대로, 그 밖의 칸은 JSON 이다. 반복 카드 목록(`cardList`)의 카드 객체 키는 그 목록 칸 키의 끝 조각
 * (`name`·`min` 등)이고, 값의 모양은 그 조각의 칸 모양이 정한다(검사는 테스트가 조각별로 한다).
 */
export type MockupValue =
  | { kind: "text" | "textarea"; text: string }
  | { kind: "chips"; items: string[] }
  | { kind: "toggle" | "select"; value: string | number | null }
  | { kind: "number"; value: number }
  | { kind: "switch"; value: boolean }
  | { kind: "statRules"; rules: Record<string, unknown>[] }
  | { kind: "statChangeRules"; rules: StatChangeRuleValue[] }
  | { kind: "icon" | "color"; value: string }
  | { kind: "image"; token: string }
  | { kind: "cardList"; cards: Record<string, unknown>[]; more: number }
  | { kind: "mediaGrid"; cells: MediaGridCell[]; selected: MediaGridPosition };

/** 스탯 규칙 한 줄 — 시드 표기 그대로(`id` 는 로더가 붙여 시드·원고에 없다). */
export type StatChangeRuleValue = { condition: string; delta: number };

/** 배치표 칸 위치 — `[인물 번호, 장면 번호]`(같은 단계의 인물·장면 칩 값에서 0부터). */
export type MediaGridPosition = { person: number; scene: number };

export type MediaGridCell = MediaGridPosition & { isHiddenInChat: boolean };

export function parseMockupValue(kind: MockupKind, body: string): MockupValue {
  switch (kind) {
    case "text":
    case "textarea":
      return { kind, text: body };
    case "image":
      return { kind, token: body.trim() };
    case "chips": {
      const items = parseJson(body);
      if (!Array.isArray(items) || !items.every((item) => typeof item === "string")) {
        throw new Error(`문자열 배열이 아니다: ${body}`);
      }
      return { kind, items };
    }
    case "toggle":
    case "select": {
      const value = parseJson(body);
      if (value !== null && typeof value !== "string" && typeof value !== "number") {
        throw new Error(`선택값은 문자열·숫자·null 이어야 한다: ${body}`);
      }
      return { kind, value };
    }
    case "number": {
      const value = parseJson(body);
      if (typeof value !== "number") throw new Error(`숫자가 아니다: ${body}`);
      return { kind, value };
    }
    case "switch": {
      const value = parseJson(body);
      if (typeof value !== "boolean") throw new Error(`true/false 가 아니다: ${body}`);
      return { kind, value };
    }
    case "icon":
    case "color": {
      const value = parseJson(body);
      if (typeof value !== "string" || value === "") throw new Error(`문자열이 아니다: ${body}`);
      return { kind, value };
    }
    case "statRules": {
      const rules = parseJson(body);
      if (!Array.isArray(rules) || !rules.every(isRecord)) throw new Error(`규칙 배열이 아니다: ${body}`);
      return { kind, rules };
    }
    case "statChangeRules":
      return parseStatChangeRules(body);
    case "cardList":
      return parseCardList(body);
    case "mediaGrid":
      return parseMediaGrid(body);
    case "group":
      throw new Error("탭 전체를 가리키는 키는 목업 값을 갖지 않는다");
    default:
      return assertNever(kind);
  }
}

function parseStatChangeRules(body: string): MockupValue {
  const value = parseJson(body);
  if (!Array.isArray(value) || value.length === 0) throw new Error(`규칙은 하나 이상인 배열이어야 한다: ${body}`);
  const rules = value.map((rule): StatChangeRuleValue => {
    if (!isRecord(rule)) throw new Error(`규칙은 객체다: ${JSON.stringify(rule)}`);
    const { condition, delta, ...rest } = rule;
    if (Object.keys(rest).length > 0) throw new Error(`규칙에 모르는 키: ${Object.keys(rest).join(", ")}`);
    if (typeof condition !== "string" || condition.trim() === "") throw new Error(`조건은 빈 글이 아니어야 한다: ${JSON.stringify(rule)}`);
    if (typeof delta !== "number" || !Number.isInteger(delta) || delta === 0) {
      throw new Error(`증감은 0이 아닌 정수다: ${JSON.stringify(rule)}`);
    }
    return { condition, delta };
  });
  return { kind: "statChangeRules", rules };
}

function parseCardList(body: string): MockupValue {
  const value = parseJson(body);
  if (!isRecord(value)) throw new Error(`카드 목록은 객체여야 한다: ${body}`);
  const { cards, more = 0, ...rest } = value;
  if (Object.keys(rest).length > 0) throw new Error(`카드 목록에 모르는 키: ${Object.keys(rest).join(", ")}`);
  if (!Array.isArray(cards) || cards.length === 0 || !cards.every(isRecord)) {
    throw new Error(`cards 는 객체가 하나 이상인 배열이어야 한다: ${body}`);
  }
  if (typeof more !== "number" || !Number.isInteger(more) || more < 0) throw new Error(`more 는 0 이상 정수다: ${body}`);
  return { kind: "cardList", cards, more };
}

function parseMediaGrid(body: string): MockupValue {
  const value = parseJson(body);
  if (!isRecord(value)) throw new Error(`배치표는 객체여야 한다: ${body}`);
  const { cells, selected, ...rest } = value;
  if (Object.keys(rest).length > 0) throw new Error(`배치표에 모르는 키: ${Object.keys(rest).join(", ")}`);
  if (!Array.isArray(cells) || cells.length === 0) throw new Error(`cells 는 칸이 하나 이상인 배열이어야 한다: ${body}`);
  const parsedCells = cells.map((cell): MediaGridCell => {
    if (!Array.isArray(cell)) throw new Error(`칸은 [인물, 장면] 또는 [인물, 장면, "hidden"] 이다: ${JSON.stringify(cell)}`);
    const parts: unknown[] = cell;
    const [person, scene, marker, ...extra] = parts;
    const isHiddenInChat = marker === "hidden";
    if (extra.length > 0 || (marker !== undefined && !isHiddenInChat)) {
      throw new Error(`칸은 [인물, 장면] 또는 [인물, 장면, "hidden"] 이다: ${JSON.stringify(cell)}`);
    }
    return { ...toPosition([person, scene]), isHiddenInChat };
  });
  return { kind: "mediaGrid", cells: parsedCells, selected: toPosition(selected) };
}

function toPosition(value: unknown): MediaGridPosition {
  if (!Array.isArray(value) || value.length !== 2) throw new Error(`위치는 [인물, 장면] 이다: ${JSON.stringify(value)}`);
  const parts: unknown[] = value;
  const [person, scene] = parts;
  if (!isIndex(person) || !isIndex(scene)) throw new Error(`위치는 0 이상 정수다: ${JSON.stringify(value)}`);
  return { person, scene };
}

function isIndex(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function parseJson(body: string): unknown {
  try {
    return JSON.parse(body);
  } catch {
    throw new Error(`JSON 으로 읽히지 않는다: ${body}`);
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
