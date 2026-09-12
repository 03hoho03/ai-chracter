import type { PreviewChatMessage } from "../api/previewStream";

export type PreviewStatDef = {
  id: string;
  name: string;
  icon: string;
  color: string;
  min: number;
  max: number;
  initial: number;
  unit?: string;
  description: string;
};

export type PreviewShortcut = {
  id: string;
  name: string;
  description: string;
  prompt: string;
};

export type PreviewSessionState = {
  // 첫 전송 전에는 서버 세션이 없다(D-7, builder-techspec.md §6-2) — buildPreviewStartState가
  // 이 필드 없이 로컬 플레이스홀더 상태를 만들 수 있어야 해서 옵셔널이다.
  previewSessionId?: string;
  contentType: "character" | "story";
  messages: PreviewChatMessage[];
  stats: Record<string, number>;
  // 스토리 전용 — 캐릭터 미리보기는 항상 빈 배열(techspec-db-schema.md §5, US-089 노트: 캐릭터는
  // 스탯/키워드북/엔딩 판단 자체를 타지 않는다).
  statDefs: PreviewStatDef[];
  shortcuts: PreviewShortcut[];
  suggestedReplies: string[];
  endingStatus: { reached: boolean; epilogue?: string };
  turnCount: number;
};
