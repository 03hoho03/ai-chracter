import { Link } from "@tanstack/react-router";
import type { RefObject } from "react";

import { toNovelReadProgress, type NovelDetailResponse } from "@/entities/novel";

type BoardOverviewPanelProps = {
  novel: NovelDetailResponse;
  /** 인물 수. 인물 목록을 아직 못 받았으면 `undefined` — 그 수는 말하지 않는다. */
  characterCount: number | undefined;
  headingRef: RefObject<HTMLHeadingElement | null>;
};

/** 아무것도 고르지 않았을 때 넓은 화면의 옆 패널 — 소설 한 줄 사실, 읽은 진행, 보드 쓰는 법. 패널이 늘 있는 것은
 * 고를 때마다 캔버스 폭이 바뀌면 보던 카드가 옆으로 밀려서다. */
export function BoardOverviewPanel({ novel, characterCount, headingRef }: BoardOverviewPanelProps) {
  const progress = toNovelReadProgress(novel.chapters);
  const facts = [
    `${novel.chapters.length}화`,
    `묶음 ${novel.batches.length}개`,
    characterCount === undefined ? undefined : `인물 ${characterCount}명`,
  ]
    .filter((part) => part !== undefined)
    .join(" · ");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        {/* 조작 대상이 아니라 포커스를 받아 두는 자리라 `tabIndex=-1` 이고 포커스 테두리를 그리지 않는다. */}
        <h2 ref={headingRef} tabIndex={-1} className="text-lg font-semibold text-foreground outline-none">
          편집 보드
        </h2>
        <p className="text-sm text-muted-foreground tabular-nums">{facts}</p>
        {progress.totalCount > 0 && (
          <p className="text-sm text-muted-foreground tabular-nums">
            다 읽은 화 {progress.finishedCount}/{progress.totalCount}
          </p>
        )}
      </div>
      <ul className="flex list-disc flex-col gap-1 pl-5 text-sm break-keep text-muted-foreground">
        <li>카드를 고르면 여기서 고쳐요. 화는 본문·제목·작가의 말을, 인물은 이름·별칭·메모를 고쳐요.</li>
        <li>카드를 끌어 자리를 옮겨도 화 순서는 바뀌지 않아요. 옮긴 자리는 자동으로 저장돼요.</li>
        <li>지금 상태를 남겨 두려면 위의 "버전"에서 저장하세요.</li>
      </ul>
      <Link
        to="/novels/$novelId"
        params={{ novelId: novel.id }}
        className="self-start text-sm font-medium text-foreground underline underline-offset-4 outline-none focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-ring"
      >
        작품 정보
      </Link>
    </div>
  );
}
