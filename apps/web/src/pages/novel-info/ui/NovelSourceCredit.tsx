import { Link } from "@tanstack/react-router";

import type { NovelDetailResponse } from "@/entities/novel";

/** 원작 표기 — `원작 · 작품명 · 캐릭터명`(스토리는 캐릭터명이 없다). 원작을 지금 볼 수 있을 때만 작품명이 그 작품으로
 * 가는 링크다(비공개로 바뀌었거나 지워진 원작은 글자만).
 *
 * 원작 썸네일은 표지가 내 생성 이미지일 때만 앞에 둔다 — 표지가 원작 썸네일이면 같은 그림이 바로 옆에 두 번 놓인다. */
export function NovelSourceCredit({ novel }: { novel: NovelDetailResponse }) {
  const thumbnailUrl = novel.cover.source === "generated" ? novel.source.thumbnailUrl : null;

  return (
    <p className="flex min-w-0 items-center gap-2 text-sm break-keep text-muted-foreground">
      {thumbnailUrl !== null && (
        <img
          src={thumbnailUrl}
          alt=""
          loading="lazy"
          decoding="async"
          className="size-8 shrink-0 rounded-md border border-foreground/10 bg-secondary object-cover"
        />
      )}
      <span className="min-w-0">
        원작 ·{" "}
        {novel.source.linkable ? (
          <Link
            to="/content/$type/$id"
            params={{ type: novel.contentType, id: novel.contentId }}
            className="rounded-sm text-foreground hover:underline focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {novel.contentTitle}
          </Link>
        ) : (
          novel.contentTitle
        )}
        {novel.characterName !== null && ` · ${novel.characterName}`}
      </span>
    </p>
  );
}
