import { Button } from "@ai-character-chat/ui/components/button";
import { Slider } from "@ai-character-chat/ui/components/slider";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode, Ref } from "react";

import { VIEWER_BAR_ROW_PX } from "../lib/pageFit";
import type { ViewerChapter, ViewerRoute } from "../model/viewerSource";
import { EpisodeLink } from "./ViewerLinks";

/** 페이지 모드의 쪽 이동. */
export type ViewerPagePosition = {
  mode: "page";
  /** 지금 화면(0부터)과 화 끝 화면을 포함한 화면 수(아직 재지 못했으면 0). 슬라이더 한 칸이 한 화면이다. */
  screen: number;
  screenCount: number;
  /** 지금 화면의 논리 쪽 표시("3–4 / 16쪽"). 본문 글꼴이 오기 전에는 없고, 그동안 슬라이더는 비활성 트랙이다. */
  pageLabel: string | undefined;
  /** 그 화면으로 바로 옮긴다. */
  onSeek: (screen: number) => void;
};

type ViewerBottomBarProps = {
  ref: Ref<HTMLDivElement>;
  id: string;
  route: ViewerRoute;
  novelId: string;
  /** 화 안의 위치 — 스크롤 모드는 진행률(0 … 1), 페이지 모드는 화면 번호와 쪽 이동. */
  position: { mode: "scroll"; progress: number } | ViewerPagePosition;
  previous: ViewerChapter | undefined;
  next: ViewerChapter | undefined;
  isVisible: boolean;
  /** 열려 있으면 아래 바 위에 붙여 그리는 보기 설정 패널. */
  settingsPanel: ReactNode;
};

/** 읽기 화면의 아래 바 — 이전 화와 다음 화, 그리고 화 안을 옮기는 표시. 화 안 위치 글자는 위 바 제목 밑에 있다.
 *
 * 페이지 모드는 한 줄(56px)이다: 이전 화 · 쪽 이동 슬라이더 · 다음 화. 줄 높이는 판형 배율 계산이 비워 두는 자리와
 * 같은 상수라 바가 판형을 덮지 않는다. 슬라이더 한 칸이 한 화면이고(펼침이면 펼침 하나), 옮기면 전환 없이 바로 그
 * 화면이 된다(위치 표시라서). 쪽 수를 재기 전(본문 글꼴이 오기 전)에도 같은 자리에 썸 없는 트랙을 두어 바 높이가
 * 바뀌지 않는다. 슬라이더의 채운 구간과 썸 윤곽은 `primary` 대신 `foreground` 로 덮는다 — 이 화면의 솔리드 채움은 화
 * 끝 "다음 화" 하나여야 해서다(포커스 윤곽은 `ring` 그대로). 이전·다음 화는 좁은 화면에서도 글자를 남긴다 — 아이콘만
 * 남기면 쪽 넘김으로 읽혀 화가 바뀌는 사고가 난다.
 *
 * 스크롤 모드는 위 가장자리의 얇은 진행 막대와 이전·다음 화 한 줄이다. 막대는 화 안에서 어디쯤인지 보이는 위치 표시라
 * 길이 변화에 전환을 두지 않는다. 보기 설정 패널은 이 바 위에 붙어 함께 오르내린다. 첫 화·마지막 화에서 막힌 버튼은
 * `aria-disabled` 다 — `disabled` 는 포커스를 빼앗아 키보드 사용자가 자리를 잃는다. 이유는 화 번호가 말하므로 문구를
 * 붙이지 않는다. */
export function ViewerBottomBar({ ref, id, route, novelId, position, previous, next, isVisible, settingsPanel }: ViewerBottomBarProps) {
  return (
    <div
      ref={ref}
      id={id}
      inert={!isVisible}
      className={cn(
        "fixed inset-x-0 bottom-0 z-30 bg-background px-safe ease-out motion-safe:transition-[transform,opacity] motion-safe:duration-200",
        !isVisible && "translate-y-full opacity-0",
      )}
    >
      {settingsPanel}
      {position.mode === "page" ? (
        <nav aria-label="화 이동" className="border-t border-border pb-safe">
          <div className="flex items-center gap-2 px-4 sm:px-6" style={{ height: VIEWER_BAR_ROW_PX }}>
            <EpisodeStepButton route={route} novelId={novelId} target={previous} direction="previous" />
            <div className="min-w-0 flex-1">
              <PageSeekSlider position={position} />
            </div>
            <EpisodeStepButton route={route} novelId={novelId} target={next} direction="next" />
          </div>
        </nav>
      ) : (
        <nav aria-label="화 이동" className="border-t border-border pb-4-safe">
          <div aria-hidden className="h-0.5 bg-secondary">
            <div className="h-full bg-foreground" style={{ width: `${Math.round(position.progress * 100)}%` }} />
          </div>
          <div className="flex items-center justify-between gap-2 px-4 pt-3 sm:px-6">
            <EpisodeStepButton route={route} novelId={novelId} target={previous} direction="previous" />
            <EpisodeStepButton route={route} novelId={novelId} target={next} direction="next" />
          </div>
        </nav>
      )}
    </div>
  );
}

function PageSeekSlider({ position }: { position: ViewerPagePosition }) {
  const { screen, screenCount, pageLabel, onSeek } = position;

  // 쪽 수를 재기 전: 같은 자리·같은 모양의 트랙만 둔다(조작할 것이 없어 보조기기에서도 뺀다).
  if (pageLabel === undefined || screenCount === 0) {
    return (
      <div aria-hidden className="flex h-10 items-center">
        <div className="h-1 w-full rounded-full bg-secondary" />
      </div>
    );
  }
  return (
    <Slider
      value={[screen + 1]}
      min={1}
      max={screenCount}
      step={1}
      thumbLabel="쪽 이동"
      thumbValueText={pageLabel}
      onValueChange={([value]) => {
        if (value !== undefined) onSeek(value - 1);
      }}
      className="h-10 [&_[data-slot=slider-range]]:bg-foreground [&_[data-slot=slider-thumb]]:size-4 [&_[data-slot=slider-thumb]]:border-foreground [&_[data-slot=slider-thumb]:focus-visible]:border-ring"
    />
  );
}

function EpisodeStepButton({
  route,
  novelId,
  target,
  direction,
}: {
  route: ViewerRoute;
  novelId: string;
  target: ViewerChapter | undefined;
  direction: "previous" | "next";
}) {
  const label = direction === "previous" ? "이전 화" : "다음 화";
  const content =
    direction === "previous" ? (
      <>
        <ChevronLeft aria-hidden />
        {label}
      </>
    ) : (
      <>
        {label}
        <ChevronRight aria-hidden />
      </>
    );

  if (target === undefined) {
    return (
      <Button type="button" variant="ghost" size="sm" aria-disabled className="aria-disabled:opacity-65">
        {content}
      </Button>
    );
  }
  return (
    <Button asChild variant="ghost" size="sm">
      <EpisodeLink route={route} novelId={novelId} chapterId={target.id}>
        {content}
      </EpisodeLink>
    </Button>
  );
}
