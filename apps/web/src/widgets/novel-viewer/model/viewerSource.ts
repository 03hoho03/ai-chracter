import type { ReactNode } from "react";

import type { SavedReadingPosition } from "../lib/toRestoreParagraphIndex";

/** 읽기 화면이 놓인 경로 — 내 소설(`/novels/…`)과 노벨(`/webnovels/…`). 링크 목적지와 화 끝의 몇 자리가 이것으로
 * 갈린다. 경로가 둘뿐이고 늘지 않아 목적지를 문자열로 주입하지 않고 이 값 하나로 고른다(라우터 `Link` 의 `to` 는
 * 리터럴 타입이라 문자열 주입은 경로 검사를 잃는다). */
export type ViewerRoute = "owner" | "public";

/** 이웃 화·화 끝·아래 바가 쓰는 화 하나. */
export type ViewerChapter = {
  id: string;
  ordinal: number;
  title: string | null;
  /** 노벨에서 아직 소장하지 않아 잠긴 화면 그 가격. 화 끝 "다음 화" 버튼이 미리 알린다. */
  lockedPrice?: number;
};

export type ViewerNovel = {
  id: string;
  title: string | null;
  chapters: readonly ViewerChapter[];
};

/** 지금 읽는 화. 문단은 서버가 나눈 그대로다. 작가의 말이 없으면 빈 글자다. */
export type ViewerEpisode = {
  id: string;
  ordinal: number;
  title: string | null;
  authorNote: string;
  paragraphs: readonly string[];
};

/** 저장하는 읽은 자리. 어느 본문의 자리인지(소유자는 개정 id, 노벨은 공개본 판)는 저장소가 붙인다. */
export type ViewerReadingPosition = {
  paragraphIndex: number;
  paragraphCount: number;
  finished: boolean;
};

/** 읽은 자리를 어디서 읽고 어디에 쓰는가. 내 소설과 노벨은 저장 주소·요청 몸·캐시가 달라 읽기 화면이 이것을 받는다.
 * 함수들은 화를 연 동안 같은 화·같은 본문을 가리킨다(화나 본문이 바뀌면 읽기 화면이 새로 마운트된다). */
export type ReadingPositionStore = {
  /** 이 화를 열 때 되돌릴 자리. 없으면 맨 위에서 연다. */
  saved: SavedReadingPosition | undefined;
  /** `saved` 가 없을 때 서버에도 자리가 없다고 확신하는가. 아니면 이용자가 스스로 움직인 뒤부터 잰다. */
  isAbsenceKnown: boolean;
  /** 이 화를 이미 다 읽었는가(그때는 다시 읽어도 다 읽은 화로 남는다). */
  wasFinished: boolean;
  save: (position: ViewerReadingPosition) => Promise<void>;
  /** 페이지가 숨거나 닫히는 순간의 저장(그때는 보통 요청이 끊겨 `keepalive` 로 보낸다). */
  sendKeepalive: (position: ViewerReadingPosition) => Promise<void>;
  /** 이 화를 떠날 때. 마지막으로 잰 자리(재지 않았으면 없다)와, 날아가던 저장이 모두 끝나면 풀리는 약속을 받는다 —
   * 캐시를 먼저 고쳐 두고 저장이 끝난 뒤 다시 받게 하는 데 쓴다. */
  onLeave: (lastRecorded: ViewerReadingPosition | undefined, settled: Promise<unknown>) => void;
};

/** 화 끝 블록이 놓인 자리의 크기 규칙. 판형 안이면 버튼·아이콘 크기를 px 로 고정한 클래스를 준다(판형 안 글자가
 * 브라우저 기본 글자 크기를 따르면 쪽 수가 바뀐다). 스크롤 모드면 비어 있다(평소 크기). */
export type EpisodeEndFormat = {
  isInPageFormat: boolean;
  buttonClassName: string | undefined;
  iconClassName: string | undefined;
};

/** 노벨 화 끝에만 더하는 자리 — 다음 화 아래 [좋아요][댓글] 줄과, 맨 아래 "이 화 신고하기". 좋아요·댓글·신고는 다른
 * 기능이라 노벨 화면이 그려 넣는다. */
export type EpisodeEndExtras = {
  renderActions: (format: EpisodeEndFormat) => ReactNode;
  renderReport: (format: EpisodeEndFormat) => ReactNode;
};
