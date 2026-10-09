import type { ReaderFontSize, ReaderLineHeight, ReaderSettings } from "../model/readerSettings";

/**
 * 페이지 모드의 판형 — 한 쪽의 논리 크기(px). 본문을 이 크기의 쪽에 조판한 뒤 판형 전체를 화면에 맞춰 키우고
 * 줄인다(`toPageFit`). 그래서 같은 글자 크기·줄 간격이면 기기·창 크기와 무관하게 한 화가 같은 쪽 수다.
 *
 * 2:3 비율이고 높이 540 은 가장 낮은 흔한 폰(브라우저 막대가 보이는 iPhone SE Safari)에서 배율이 하한 위에 남는 가장
 * 큰 값이다. 폭 360 은 폰에서 배율이 1 안팎이 되는 값이다 — 넓히면 한 줄이 길어지는 대신 같은 폰에서 글자가 작아진다.
 * 안쪽 여백은 사방 같고, 펼침의 두 쪽 사이 글 간격은 양쪽 여백의 합(48)이다.
 */
export const PAGE_FORMAT_WIDTH_PX = 360;
export const PAGE_FORMAT_HEIGHT_PX = 540;
export const PAGE_FORMAT_PADDING_PX = 24;

/** 판형 안 글 상자(여백을 뺀 단)의 크기. */
export const PAGE_TEXT_WIDTH_PX = PAGE_FORMAT_WIDTH_PX - 2 * PAGE_FORMAT_PADDING_PX;
export const PAGE_TEXT_HEIGHT_PX = PAGE_FORMAT_HEIGHT_PX - 2 * PAGE_FORMAT_PADDING_PX;

/** 스크롤 모드 클래스(`text-sm`·`text-lg`·`text-xl`)가 브라우저 기본 글자 크기에서 내는 값과 같은 px. */
const FONT_SIZE_PX = { small: 16, medium: 18, large: 20 } satisfies Record<ReaderFontSize, number>;

/** 스크롤 모드 클래스(`leading-normal`·`leading-relaxed`·`leading-loose`)와 같은 배수. */
const LINE_HEIGHT_RATIO = { normal: 1.5, relaxed: 1.625, loose: 2 } satisfies Record<ReaderLineHeight, number>;

export type PageTypography = {
  fontSizePx: number;
  /** 단위 없는 줄 간격 배수 — 계산값은 글자 크기 × 배수(px)다. */
  lineHeight: number;
  /** 문단 사이 간격. 글자 크기와 같아, 글자를 키워도 문단 사이가 상대적으로 좁아지지 않는다. */
  paragraphGapPx: number;
};

/**
 * 보기 설정에서 판형 안 조판값을 정한다. 전부 px 다 — 저장소가 `html` 글자 크기를 정하지 않아 rem 이면 브라우저 기본
 * 글자 크기를 바꾼 사람에게서 같은 판형의 쪽 수가 달라진다.
 */
export function toPageTypography({ fontSize, lineHeight }: Pick<ReaderSettings, "fontSize" | "lineHeight">): PageTypography {
  const fontSizePx = FONT_SIZE_PX[fontSize];
  return { fontSizePx, lineHeight: LINE_HEIGHT_RATIO[lineHeight], paragraphGapPx: fontSizePx };
}
