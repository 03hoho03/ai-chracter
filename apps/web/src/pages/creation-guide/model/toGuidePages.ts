import { assertNever } from "@/shared/lib/assertNever";

import type { GuideTopic } from "../config/topics";
import type { GuideItem, Manuscript, ManuscriptSection, SectionContent } from "./parseManuscript";

export type GuideStep = {
  /** 빌더 탭 id 이자 단계 페이지 경로 조각. */
  id: string;
  /** 0부터. 화면의 단계 번호는 `index + 1`. */
  index: number;
  /** 빌더 탭 라벨(단계 칩 글자). */
  label: string;
  /** `N단계 · 탭 라벨`. */
  title: string;
  /** 개요 단계 행 둘째 줄. 원고의 요약 표기가 없으면(캐릭터) 첫 산문 문단이다 — 화면이 한 줄로 자른다. */
  summary: string;
  /** 단계 머리의 리드 문단. 칸 블록을 쓰는 토픽만 따로 떼어 둔다(나머지 토픽은 null 이고 `content` 에 그대로 있다). */
  lead: string | null;
  content: SectionContent[];
  prevId: string | null;
  nextId: string | null;
};

export type GuideAnchor = { stepId: string; anchorId: string };

export type GuidePages = {
  /**
   * 개요 페이지에 들어갈 절. `before` 는 원고에서 첫 단계 앞, `after` 는 마지막 단계 뒤에 있던 절이다. 화면 순서는 원고
   * 순서와 다르다 — 들어가며 → 단계 행 → `before` 의 나머지(스토리의 AI가 칸을 읽는 때) → `after`(미리보기·자주 하는
   * 실수).
   */
  overview: { before: ManuscriptSection[]; after: ManuscriptSection[] };
  steps: GuideStep[];
  /** 칸 키 → 그 키를 품은 블록의 단계와 앵커. 개요 "AI가 읽는 때" 목록의 칸 링크가 쓴다. */
  anchorOfKey: ReadonlyMap<string, GuideAnchor>;
};

/**
 * 파싱한 원고를 개요 페이지 하나와 단계 페이지들로 나눈다. 원고의 단계 절이 빌더 탭과 1:1(순서·연속·제목)인지,
 * 칸 블록이 단계 절 안에만 있는지 여기서 확인하고 어긋나면 던진다 — 단계 페이지 라우트가 탭 id 로 단계를 찾기 때문에,
 * 어긋난 원고는 화면에서 단계가 빠지거나 엉뚱한 탭의 글이 보이는 식으로만 드러난다.
 */
export function toGuidePages(manuscript: Manuscript, topic: GuideTopic): GuidePages {
  const stepIds = topic.steps.map((step) => step.id);
  const stepPositions = manuscript.sections.flatMap((section, position) =>
    stepIds.includes(section.id) ? [position] : [],
  );
  const firstPosition = stepPositions[0] ?? 0;
  const stepSections = manuscript.sections.slice(firstPosition, firstPosition + stepIds.length);

  if (stepSections.map((section) => section.id).join(" ") !== stepIds.join(" ")) {
    throw new Error(
      `${topic.id} 원고의 단계 절이 빌더 탭 순서와 다르다(연속해야 한다): ${stepSections.map((section) => section.id).join(", ")}`,
    );
  }

  const usesFieldBlocks = topic.fieldMockups !== undefined;
  const anchorOfKey = new Map<string, GuideAnchor>();

  const steps = stepSections.map((section, index): GuideStep => {
    const tab = topic.steps[index];
    if (!tab) throw new Error(`${topic.id} 원고에 탭이 없는 단계 절: ${section.id}`);
    const title = `${index + 1}단계 · ${tab.label}`;
    if (section.title !== title) throw new Error(`${section.line}번째 줄 단계 제목은 "${title}" 이어야 한다`);

    for (const item of section.content) {
      if (item.kind !== "field") continue;
      for (const key of item.keys) {
        if (usesFieldBlocks && !(key in (topic.fieldMockups ?? {}))) {
          throw new Error(`${item.line}번째 줄: 목업 표에 없는 칸 키 ${key}`);
        }
        if (anchorOfKey.has(key)) throw new Error(`${item.line}번째 줄: 칸 키 ${key} 가 두 블록에 나온다`);
        anchorOfKey.set(key, { stepId: section.id, anchorId: item.id });
      }
    }

    const { lead, content } = usesFieldBlocks ? splitLead(section) : { lead: null, content: section.content };
    return {
      id: section.id,
      index,
      label: tab.label,
      title,
      summary: section.summary ?? firstParagraph(section.content),
      lead,
      content,
      prevId: stepIds[index - 1] ?? null,
      nextId: stepIds[index + 1] ?? null,
    };
  });

  const before = manuscript.sections.slice(0, firstPosition);
  const after = manuscript.sections.slice(firstPosition + stepIds.length);
  for (const section of [...before, ...after]) {
    if (stepIds.includes(section.id)) throw new Error(`${section.line}번째 줄: 단계 절 ${section.id} 가 한 번 더 나온다`);
    if (section.summary !== null) throw new Error(`${section.line}번째 줄: 요약 표기는 단계 절에만 쓴다`);
    const block = section.content.find((item) => item.kind === "field" || item.kind === "note");
    if (block) throw new Error(`${section.line}번째 줄: 칸 블록·칸 아닌 블록은 단계 절에만 쓴다`);
  }
  if (!usesFieldBlocks) {
    for (const section of stepSections) {
      const block = section.content.find((item) => item.kind === "field" || item.kind === "note");
      if (block) throw new Error(`${section.line}번째 줄: ${topic.id} 토픽은 목업 표가 없어 칸 블록을 쓸 수 없다`);
    }
  }

  return { overview: { before, after }, steps, anchorOfKey };
}

/**
 * 칸 블록을 쓰는 토픽의 단계 절은 "요약 표기 → 리드 한 문단 → 블록들" 모양이어야 한다. 리드 뒤에 블록 아닌 글이 섞이면
 * 단계 머리 아래 칸에 붙지 않은 글이 떠서 칸 단위 구성이 무너지므로 던진다.
 */
function splitLead(section: ManuscriptSection): { lead: string; content: SectionContent[] } {
  const [first, ...rest] = section.content;
  if (section.summary === null) throw new Error(`${section.line}번째 줄 단계 절에 요약 표기(::: summary)가 없다`);
  if (first?.kind !== "markdown") throw new Error(`${section.line}번째 줄 단계 절이 리드 문단으로 시작하지 않는다`);
  const stray = rest.find((item) => item.kind === "markdown" || item.kind === "example");
  if (stray) throw new Error(`${section.line}번째 줄 단계 절: 리드 뒤에는 블록만 둔다(칸에 안 붙는 글은 note 나 자세히로)`);
  return { lead: first.source, content: rest };
}

/** 첫 산문 조각의 첫 문단(제목 줄 제외)을 굵게 표기를 뺀 평문으로. */
function firstParagraph(content: readonly SectionContent[]): string {
  for (const item of content) {
    if (item.kind !== "markdown") continue;
    const paragraph = item.source
      .split(/\n\s*\n/)
      .map((block) => block.trim())
      .find((block) => block !== "" && !block.startsWith("#"));
    if (paragraph) return paragraph.replace(/\*\*/g, "");
  }
  return "";
}

export type ConversationMessage = { role: "character" | "user"; body: string };

/** 화면에 그리는 산문 단위. 연달아 오는 채팅 예시는 대화 한 판으로 묶는다. */
export type GuideDisplayItem =
  | { kind: "markdown"; source: string }
  | { kind: "conversation"; messages: ConversationMessage[] }
  | { kind: "field"; body: string };

/**
 * 산문 조각 목록을 화면 단위로 묶는다 — 연달아 오는 `chat`·`chat-user` 예시는 대화 한 판이다. 실제 채팅처럼 메시지 사이
 * 간격으로 이어져야 "여기서 다른 사람의 말이 시작된다"가 읽히고, 따로 그리면 예시 상자 여러 개로 끊어져 보인다.
 * 묶음은 목록 하나 안에서만 생긴다 — 블록 본문·자세히·나쁜 예의 경계를 넘지 않는다.
 */
export function toDisplayItems(items: readonly GuideItem[]): GuideDisplayItem[] {
  const display: GuideDisplayItem[] = [];
  for (const item of items) {
    if (item.kind === "markdown") {
      display.push({ kind: "markdown", source: item.source });
      continue;
    }
    const { example } = item;
    switch (example.kind) {
      case "field":
        display.push({ kind: "field", body: example.body });
        break;
      case "chat":
        appendMessage(display, { role: "character", body: example.body });
        break;
      case "chat-user":
        appendMessage(display, { role: "user", body: example.body });
        break;
      default:
        assertNever(example.kind);
    }
  }
  return display;
}

function appendMessage(display: GuideDisplayItem[], message: ConversationMessage) {
  const last = display.at(-1);
  if (last?.kind === "conversation") {
    last.messages.push(message);
  } else {
    display.push({ kind: "conversation", messages: [message] });
  }
}

/**
 * 옛 한 페이지 가이드의 단계 앵커(`/guide/story#setting`)로 들어온 링크를 단계 페이지 id 로 바꾼다. 해시는 서버에 가지
 * 않아 화면에서만 처리할 수 있다. 탭 id 와 정확히 같은 해시만 옮기고, 개요 안의 앵커(`#preview` 등)는 그대로 둔다 —
 * 그래야 개요 안 이동이 단계 페이지로 튀지 않는다.
 */
export function legacyStepFromHash(hash: string, stepIds: readonly string[]): string | null {
  const id = hash.startsWith("#") ? hash.slice(1) : hash;
  return stepIds.includes(id) ? id : null;
}
