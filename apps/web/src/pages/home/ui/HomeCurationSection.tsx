import { useId } from "react";
import { cn } from "@ai-character-chat/ui/lib/utils";
import { ImageOff } from "lucide-react";

import {
  toGridColumns,
  toThumbnailAspect,
  toThumbnailAspectClass,
  type ContentType,
  type HomeCurationItem,
} from "@/entities/content";

import { toHomeCurationHeading } from "../model/homeCuration";

type HomeCurationSectionProps = {
  item: HomeCurationItem;
  onOpen: (type: ContentType, id: string) => void;
};

/** 운영자가 그 유형에 걸어 둔 한 편. 필터 행 아래·그리드 바로 위에 놓인다.
 *
 * 카드 전체가 상세 모달을 여는 하나의 클릭 영역이다(안에 다른 버튼이 없다) — 바깥은 그리드의 `ContentCard`와 같은
 * `role="button"` div 이고, 껍데기(배경·보더·hover)가 없는 것도, 포커스 링·눌림 표시도 같다. 강조는 솔리드 버튼이
 * 아니라 크기와 배치로 만든다: 그림 옆에 제목과 한 줄 소개를 가로로 펼쳐 그리드 카드보다 말이 많다.
 *
 * 640px 이상에서는 바로 아래 그리드와 같은 열 사다리(`toGridColumns`) 위에 놓는다: 그림이 한 열, 제목·소개가 두 열을
 * 차지한다. 그래서 그림은 어느 폭에서나 그리드 카드 그림과 같은 크기이고, 블록은 그리드 세 칸 폭이라 행 끝까지
 * 늘어나지 않는다(열이 셋뿐인 640~767px 캐릭터 화면에서만 행 전체다). 그보다 좁으면 그림을 `w-28`(112px)로
 * 고정하고 제목·소개가 나머지 폭을 쓴다. 그림 크기의 천장은 그리드 카드다: 같은 512px 썸네일 축소본을 그리드가 이미
 * 그 크기로 그리므로 선명도가 그리드와 같고, 그보다 키우면 큐레이션만 흐려진다.
 *
 * 첫 화면 안에 있으므로 지연 로드하지 않지만(`eager`) 우선순위는 올리지 않는다. 높은 우선순위는 그리드 첫 카드에
 * 둔다. 640px 이상에서는 이 그림이 그리드 카드와 크기가 같고 더 위에 있어 LCP 요소가 될 수 있다. 큐레이션 작품이
 * 그리드 첫 행에도 있으면 같은 서명 주소라 요청이 하나로 합쳐져 손해가 없지만, 첫 행에 없으면 이 그림이 보통
 * 우선순위로 따로 받아져 LCP 가 그만큼 늦어질 수 있다. */
export function HomeCurationSection({ item, onOpen }: HomeCurationSectionProps) {
  const id = useId();
  const headingId = `${id}-heading`;
  const nameId = `${id}-name`;
  const oneLinerId = `${id}-one-liner`;
  const thumbnailAspect = toThumbnailAspect(item.type);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="text-sm font-medium text-muted-foreground">
        {toHomeCurationHeading(item.type)}
      </h2>
      {/* 640px 미만에서는 블록 요소라 열 클래스가 효력이 없다 — 모바일 배치는 아래 버튼의 flex 가 정한다. */}
      <div className={cn("sm:grid sm:gap-3", toGridColumns(thumbnailAspect))}>
        <div
          role="button"
          tabIndex={0}
          aria-labelledby={`${nameId} ${oneLinerId}`}
          onClick={() => onOpen(item.type, item.id)}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            onOpen(item.type, item.id);
          }}
          className="flex w-full max-w-xl cursor-pointer items-start gap-4 rounded-xl text-left focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px sm:col-span-3 sm:grid sm:max-w-none sm:grid-cols-3 sm:gap-3"
        >
          <div
            className={cn(
              toThumbnailAspectClass(thumbnailAspect),
              "w-28 shrink-0 overflow-hidden rounded-xl border border-foreground/10 bg-secondary sm:w-auto",
            )}
          >
            {item.thumbnailUrl ? (
              <img
                src={item.thumbnailUrl}
                alt=""
                loading="eager"
                decoding="async"
                className="size-full object-cover"
              />
            ) : (
              <div className="flex size-full items-center justify-center text-muted-foreground">
                <ImageOff aria-hidden />
              </div>
            )}
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:col-span-2">
            <p id={nameId} className="line-clamp-2 break-keep break-words text-lg font-semibold text-foreground sm:text-xl sm:tracking-tight">
              {item.name}
            </p>
            <p id={oneLinerId} className="line-clamp-4 break-keep break-words text-sm text-muted-foreground">
              {item.oneLiner}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
