import type { ReaderFontSize, ReaderLineHeight, ReaderSettings } from "../model/readerSettings";

/** 단계마다 완전한 클래스 이름을 문자열 그대로 적는다. Tailwind 는 소스의 글자를 훑어 클래스를 만들기 때문에
 * `text-${size}` 처럼 조합하면 빌드에 그 클래스가 생기지 않는다.
 *
 * 글자 크기에 `text-base` 가 없는 이유: 이 저장소는 `--text-sm` 을 `1rem` 으로 올려 `text-base` 와 같은 값이라
 * 구분되는 단계가 `text-sm`·`text-lg`·`text-xl` 셋이다(천장 `text-2xl` 안). 줄 간격은 Tailwind 기본 스케일의 끝이
 * `leading-loose` 다. */
const FONT_SIZE_CLASS = {
  small: "text-sm",
  medium: "text-lg",
  large: "text-xl",
} satisfies Record<ReaderFontSize, string>;

const LINE_HEIGHT_CLASS = {
  normal: "leading-normal",
  relaxed: "leading-relaxed",
  loose: "leading-loose",
} satisfies Record<ReaderLineHeight, string>;

export function readerTypographyClassName(settings: ReaderSettings): string {
  return `${FONT_SIZE_CLASS[settings.fontSize]} ${LINE_HEIGHT_CLASS[settings.lineHeight]}`;
}
