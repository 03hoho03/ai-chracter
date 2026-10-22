import type { GeneratedImageItem } from "@/entities/generated-image";
import { isApiError } from "@/shared/api/client";

type NovelUsage = GeneratedImageItem["novelUsages"][number];

const NOVEL_FIELD_LABEL: Record<NovelUsage["field"], string> = {
  cover: "표지",
  illustration: "삽화",
};

/** 소설 사용처 한 줄. 링크가 아니다 — 사용처에는 작가가 지워 숨긴 팔린 소설의 남긴 판도 들어오는데 응답에 숨김 여부가
 * 없어, 링크를 걸면 그 줄은 지워진 소설 화면으로 간다. */
export type NovelUsageRow = { key: string; title: string; detail: string };

export type GeneratedImageUsageView = {
  /** 작품이나 소설 어디서든 쓰이면 참 — 서버가 삭제를 막는다. */
  isInUse: boolean;
  /** 보관함 배지 수(작품 + 소설 사용처). */
  usageCount: number;
  heading: string;
  /** 삭제 버튼 옆 비활성 사유. */
  deleteBlockedReason: string;
  novelRows: NovelUsageRow[];
};

/**
 * 생성 이미지 상세·보관함이 사용처를 그리는 값. 소설 사용처가 없으면(삽화 스위치를 켠 적 없으면 늘 그렇다) 머리·사유
 * 문장이 지금 화면 그대로다 — 작품만 말한다. 남의 소설(원작 그림으로 붙인 다른 작가)은 서버가 id·제목을 비워 보내므로
 * 제목 없이 말한다. 소설 칸이 없는 응답(그 칸을 더하기 전 API)은 빈 목록으로 읽는다.
 */
export function toGeneratedImageUsageView(image: {
  usages: readonly unknown[];
  novelUsages?: readonly NovelUsage[];
}): GeneratedImageUsageView {
  const novelUsages = image.novelUsages ?? [];
  const usageCount = image.usages.length + novelUsages.length;
  const hasNovelUsage = novelUsages.length > 0;
  return {
    isInUse: usageCount > 0,
    usageCount,
    heading: hasNovelUsage ? "사용 중인 곳" : "사용 중인 작품",
    deleteBlockedReason: hasNovelUsage
      ? "위에서 사용 중이라 삭제할 수 없어요."
      : "위 작품에서 사용 중이라 삭제할 수 없어요.",
    novelRows: novelUsages.map((usage) =>
      usage.novelId === null
        ? { key: `other-${usage.field}`, title: "다른 작가의 소설", detail: "원작 이미지로 쓰는 중" }
        : {
            key: `${usage.novelId}-${usage.field}`,
            title: usage.novelTitle || "제목 없음",
            detail: NOVEL_FIELD_LABEL[usage.field],
          },
    ),
  };
}

/** 삭제가 409(그사이 어딘가에 쓰임)로 막혔을 때의 문장. 응답이 소설 사용처를 실었으면 소설도 말한다. */
export function toGeneratedImageDeleteConflictMessage(error: unknown): string {
  const detail = isApiError(error) && typeof error.detail === "object" && error.detail !== null ? error.detail : undefined;
  const novelUsages = detail !== undefined && "novelUsages" in detail ? detail.novelUsages : undefined;
  return Array.isArray(novelUsages) && novelUsages.length > 0
    ? "이미지가 방금 작품이나 소설에 사용되어 삭제할 수 없어요."
    : "이미지가 방금 작품에 사용되어 삭제할 수 없어요.";
}
