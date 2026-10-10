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

/**
 * 작가 글의 `{{user}}`·`{{char}}` 를 고를 때 쓰는 작품 쪽 값. 서버는 세션을 시작할 때 받은 페이로드를 세션 내내 쓰므로
 * (세션 중에 페이로드를 바꾸는 경로가 없다) 화면도 같은 순간의 값을 세션 상태에 들고 있다 — 세션 도중 폼에서 이름을
 * 고쳐도 모델이 아는 이름과 화면·보내는 글의 이름이 갈리지 않는다. 새 세션(미리보기 초기화)에서 다시 잡힌다.
 */
export type PreviewAuthorNameSource = {
  /** 작품 이름 — 캐릭터 미리보기에서 `{{char}}` 가 된다. */
  contentName: string;
};

export type PreviewSessionState = {
  // 첫 전송 전에는 서버 세션이 없다 — buildPreviewStartState가
  // 이 필드 없이 로컬 플레이스홀더 상태를 만들 수 있어야 해서 옵셔널이다.
  previewSessionId?: string;
  contentType: "character" | "story";
  authorNameSource: PreviewAuthorNameSource;
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
