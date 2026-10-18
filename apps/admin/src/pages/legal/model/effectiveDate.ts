import { toKstDateString } from "@/shared/lib/format/kstDate";

// 시행 시각은 한국 시각 자정으로만 고른다. 어드민 화면에는 테스트 러너가 없어서, 문자열 형식을 타입으로 묶고 계산은
// 브라우저 시간대에 기대지 않는 UTC 산술로만 한다.

/** `YYYY-MM-DD` 꼴 문자열. `toKstDateString()` 과 `<input type="date">` 의 값이 이 형식이다. */
export type KstDateString = `${number}-${number}-${number}`;

const KST_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 24 * 60 * 60 * 1000;

/** 회원에게 불리한 약관 변경은 시행일 30일 전에 공지해야 한다(약관 제4조 제3항). */
export const ADVERSE_CHANGE_NOTICE_DAYS = 30;

export function isKstDateString(value: string): value is KstDateString {
  return KST_DATE_PATTERN.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`));
}

/** 그 날짜의 한국 시각 00:00 을 시간대가 붙은 ISO 문자열로. 서버는 시간대 없는 시각을 받지 않는다. */
export function kstMidnightIso(date: KstDateString): string {
  return `${date}T00:00:00+09:00`;
}

/** 두 날짜 사이의 날 수(`to - from`). 같은 날이면 0. 둘 다 같은 기준(UTC 자정)으로 읽어 시간대·서머타임이 끼지 않는다. */
export function daysBetween(from: KstDateString, to: KstDateString): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

/** 지금의 한국 날짜. */
export function todayKst(): KstDateString {
  return toKstDate(new Date());
}

/** 그 순간의 한국 날짜. 서버 시각(`effectiveAt` 등)을 날짜로만 보일 때 쓴다 — 브라우저 시간대와 무관하다. */
export function toKstDate(value: string | Date): KstDateString {
  return asKstDate(toKstDateString(value));
}

/** 다음 날짜. 오늘의 00:00 은 이미 지난 시각이라 고를 수 있는 가장 이른 시행일이 내일이다. */
export function nextKstDate(date: KstDateString): KstDateString {
  return asKstDate(new Date(Date.parse(`${date}T00:00:00Z`) + DAY_MS).toISOString().slice(0, 10));
}

// 위 두 곳의 입력은 늘 `YYYY-MM-DD` 를 내는 포매터라 여기서 던질 일은 없다. 던지게 둔 것은 형식이 바뀌었을 때 틀린 시행
// 시각을 조용히 보내지 않기 위해서다.
function asKstDate(value: string): KstDateString {
  if (!isKstDateString(value)) throw new Error(`날짜 형식이 YYYY-MM-DD 가 아닙니다: ${value}`);
  return value;
}
