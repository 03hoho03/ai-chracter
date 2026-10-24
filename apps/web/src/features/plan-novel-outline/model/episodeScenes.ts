import type { NovelEpisodeOutlineView, NovelSceneInput } from "@/entities/novel";

import { countOutlineChars, OUTLINE_GOAL_MAX_LENGTH, OUTLINE_SUMMARY_MAX_LENGTH, type OutlineRange } from "./outlineEdits";

/** 화면이 고치는 장면 하나. 장면의 근거와 등장인물은 고치지 않는다(빼기·차례·글·회상 표시만) — 근거를 바꾸려면 전체 구성안에서 화를
 * 나누거나 합친다. */
export type SceneDraft = {
  /** 화면 안 열쇠 — 서버 장면 id 그대로다(이 화면은 장면을 새로 만들지 않는다). */
  localId: string;
  id: string;
  title: string;
  /** 장면 내용. */
  summary: string;
  /** 장면 목적. 비어도 된다. */
  purpose: string;
  characters: readonly string[];
  flashback: boolean;
  basis: readonly OutlineRange[];
};

export type SceneText = Pick<SceneDraft, "title" | "summary" | "purpose">;

/** 장면 내용·목적 길이 상한(서버 검증과 같은 값 — 전체 구성안의 줄거리·목표와 같은 칸 규칙이다). 제목 상한은 상세의
 * `limits.chapterTitleMaxLength` 를 쓴다. */
export const SCENE_SUMMARY_MAX_LENGTH = OUTLINE_SUMMARY_MAX_LENGTH;
export const SCENE_PURPOSE_MAX_LENGTH = OUTLINE_GOAL_MAX_LENGTH;

export function toSceneDrafts(view: NovelEpisodeOutlineView): SceneDraft[] {
  return view.scenes.map((scene) => ({
    localId: scene.id,
    id: scene.id,
    title: scene.title,
    summary: scene.summary,
    purpose: scene.purpose,
    characters: scene.characters,
    flashback: scene.flashback,
    basis: scene.basis.map((range) => ({ startMessageId: range.startMessageId, endMessageId: range.endMessageId })),
  }));
}

/** 고친 장면 목록이 서버 판과 같은가(차례·글·회상 표시). 근거·등장인물은 이 화면이 바꾸지 않아 장면 id 로 함께 같다. */
export function isSameAsSceneView(scenes: readonly SceneDraft[], view: NovelEpisodeOutlineView): boolean {
  if (scenes.length !== view.scenes.length) return false;
  return scenes.every((scene, index) => {
    const original = view.scenes[index];
    return (
      original !== undefined &&
      original.id === scene.id &&
      original.title === scene.title &&
      original.summary === scene.summary &&
      original.purpose === scene.purpose &&
      original.flashback === scene.flashback
    );
  });
}

export function updateSceneText(scenes: readonly SceneDraft[], localId: string, text: SceneText): SceneDraft[] {
  return scenes.map((scene) => (scene.localId === localId ? { ...scene, ...text } : scene));
}

export function toggleFlashback(scenes: readonly SceneDraft[], localId: string): SceneDraft[] {
  return scenes.map((scene) => (scene.localId === localId ? { ...scene, flashback: !scene.flashback } : scene));
}

/** 장면 차례를 한 칸 옮긴다. 장면 차례는 자유다(회상 장면을 앞에 둘 수 있다) — 원고는 이 차례대로 장면을 쓴다. */
export function moveScene(scenes: readonly SceneDraft[], localId: string, delta: -1 | 1): SceneDraft[] {
  const index = scenes.findIndex((scene) => scene.localId === localId);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= scenes.length) return [...scenes];
  const next = [...scenes];
  const [moved] = next.splice(index, 1);
  if (moved !== undefined) next.splice(target, 0, moved);
  return next;
}

export function toSceneMoveBlockedReason(scenes: readonly SceneDraft[], localId: string, delta: -1 | 1): string | undefined {
  const index = scenes.findIndex((scene) => scene.localId === localId);
  if (delta === -1 && index <= 0) return "맨 앞 장면이에요.";
  if (delta === 1 && index >= scenes.length - 1) return "맨 뒤 장면이에요.";
  return undefined;
}

/** 장면을 뺀다. 뺀 장면의 근거 대화는 원고에 쓰지 않는다(서버 규칙 — 화 근거 안에서 장면이 덮지 않는 턴은 쓰지 않는다). */
export function removeScene(scenes: readonly SceneDraft[], localId: string): SceneDraft[] {
  return scenes.filter((scene) => scene.localId !== localId);
}

export function toSceneRemoveBlockedReason(scenes: readonly SceneDraft[]): string | undefined {
  return scenes.length <= 1 ? "장면 구성안에는 장면이 하나 이상 있어야 해요." : undefined;
}

/** 저장 몸. 장면 id·근거·등장인물은 그대로 보내고, 글은 서버처럼 앞뒤 공백을 걷는다. */
export function toSaveScenes(scenes: readonly SceneDraft[]): NovelSceneInput[] {
  return scenes.map((scene) => ({
    id: scene.id,
    title: scene.title.trim(),
    summary: scene.summary.trim(),
    purpose: scene.purpose.trim(),
    characters: [...scene.characters],
    flashback: scene.flashback,
    basis: scene.basis.map((range) => ({ startMessageId: range.startMessageId, endMessageId: range.endMessageId })),
  }));
}

/** 저장 전에 고칠 것 — 서버가 같은 이유로 막는 것을 장면 번호로 먼저 짚는다. 고치기 폼이 같은 규칙으로 막으므로 대개 비어 있다. */
export function toSceneProblems(scenes: readonly SceneDraft[], limits: { titleMaxLength: number }): string[] {
  return scenes.flatMap((scene, index) => {
    const label = `장면 ${index + 1}`;
    const problems: string[] = [];
    const titleLength = countOutlineChars(scene.title);
    const summaryLength = countOutlineChars(scene.summary);
    if (titleLength === 0) problems.push(`${label} 제목을 적어주세요.`);
    else if (titleLength > limits.titleMaxLength) {
      problems.push(`${label} 제목은 ${limits.titleMaxLength.toLocaleString()}자까지 쓸 수 있어요.`);
    }
    if (summaryLength === 0) problems.push(`${label} 내용을 적어주세요.`);
    else if (summaryLength > SCENE_SUMMARY_MAX_LENGTH) {
      problems.push(`${label} 내용은 ${SCENE_SUMMARY_MAX_LENGTH.toLocaleString()}자까지 쓸 수 있어요.`);
    }
    if (countOutlineChars(scene.purpose) > SCENE_PURPOSE_MAX_LENGTH) {
      problems.push(`${label} 목적은 ${SCENE_PURPOSE_MAX_LENGTH.toLocaleString()}자까지 쓸 수 있어요.`);
    }
    return problems;
  });
}
