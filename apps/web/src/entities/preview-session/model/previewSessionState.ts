import type { MediaTagImages } from "@/entities/media-book/@x/preview-session";

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
  // 첫 전송 전에는 서버 세션이 없다 — buildPreviewStartState가
  // 이 필드 없이 로컬 플레이스홀더 상태를 만들 수 있어야 해서 옵셔널이다.
  previewSessionId?: string;
  contentType: "character" | "story";
  messages: PreviewChatMessage[];
  // 첫 메시지(작성자의 시작상황·프롤로그)의 칸 id 형태 태그가 가리키는 그림. 빌더가 가진 칸 썸네일로 만든다.
  openingMediaTagImages: MediaTagImages;
  stats: Record<string, number>;
  // 스토리 전용 — 캐릭터 미리보기는 항상 빈 배열(캐릭터는
  // 스탯/키워드북/엔딩 판단 자체를 타지 않는다).
  statDefs: PreviewStatDef[];
  shortcuts: PreviewShortcut[];
  suggestedReplies: string[];
  // `mediaTagImages` 는 에필로그의 칸 id 형태 태그가 가리키는 그림이다(엔딩 도달 이벤트에 실려 온다).
  endingStatus: { reached: boolean; epilogue?: string; mediaTagImages?: MediaTagImages };
  turnCount: number;
};
