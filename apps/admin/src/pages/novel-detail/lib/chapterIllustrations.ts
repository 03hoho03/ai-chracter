import type { CSSProperties } from "react";

import type { AdminNovelIllustration } from "@/entities/admin-novel";

export const ILLUSTRATION_SOURCE_LABELS: Record<AdminNovelIllustration["source"], string> = {
  upload: "작가가 올린 그림",
  original: "원작 이미지",
  generated: "생성한 그림",
};

/** 그림 자리 하나(앞뒤·문단 번호)의 그림들을 `order` 순으로 돌려준다. */
type IllustrationSpot = (
  placement: AdminNovelIllustration["placement"],
  paragraphIndex: number,
) => AdminNovelIllustration[];

/**
 * 화 응답의 그림을 (문단 번호, 앞뒤) 자리로 한 번 묶어, 자리를 주면 그 자리 그림을 돌려주는 함수를 만든다. 응답에
 * `illustrations` 칸이 없으면(그 칸이 생기기 전 API) 그림 없는 화로 본다 — 화면이 깨지지 않고 글만 보인다.
 */
export function illustrationSpots(chapter: { illustrations?: readonly AdminNovelIllustration[] }): IllustrationSpot {
  const spots = new Map<string, AdminNovelIllustration[]>();
  for (const illustration of chapter.illustrations ?? []) {
    const key = `${illustration.paragraphIndex}-${illustration.placement}`;
    spots.set(key, [...(spots.get(key) ?? []), illustration]);
  }
  for (const list of spots.values()) list.sort((a, b) => a.order - b.order);
  return (placement, paragraphIndex) => spots.get(`${paragraphIndex}-${placement}`) ?? [];
}

/** 화 안에서 그림 자리 하나를 가리키는 렌더 키 — 같은 자산이 한 화에 두 번 붙을 수 있어 자산 id 가 아니라 자리로 만든다. */
export function illustrationKey(illustration: AdminNovelIllustration): string {
  return `${illustration.paragraphIndex}-${illustration.placement}-${illustration.order}`;
}

/** 운영자 화면의 그림 대체 글 — 어느 문단 앞뒤의 몇째 그림인지 말한다(운영자에게는 장식이 아니라 확인할 대상이고, 같은 자리에
 * 그림이 여럿이면 "그림 내리기" 버튼의 접근 이름이 이 글로 갈린다). */
export function illustrationAlt(illustration: AdminNovelIllustration): string {
  const spot = `${illustration.paragraphIndex + 1}번째 문단 ${illustration.placement === "before" ? "앞" : "뒤"} 삽화`;
  return illustration.order === 0 ? spot : `${spot} ${illustration.order + 1}`;
}

/**
 * 크기를 아는 그림의 틀 — 폭을 "높이가 `maxHeight` 에 닿는 폭"으로 못박고 `max-width: 100%` 로 열 폭에 맞춰 줄인다(비율 틀에
 * 높이 상한을 걸면 폭이 줄지 않아 그림이 잘린다). 그림이 오기 전에 높이가 정해져 아래 글이 밀리지 않는다. 크기를 모르면 undefined.
 */
export function illustrationFrameStyle(
  width: number | null,
  height: number | null,
  maxHeight: number,
): CSSProperties | undefined {
  if (!width || !height || width <= 0 || height <= 0) return undefined;
  return { aspectRatio: `${width} / ${height}`, width: `${Math.round((maxHeight * width) / height)}px`, maxWidth: "100%" };
}
