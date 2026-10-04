import { findGuideImage } from "../config/guideImages";
import type { GuideMockupContext } from "../model/guideMockupContext";

type GuideExampleWorkProps = {
  context: GuideMockupContext;
};

/**
 * 개요의 예시 작품 소개 — 표지·이름·한줄소개. 값은 프로필 단계 칸 그림과 같은 원고 값이라 두 곳이 어긋나지 않는다.
 *
 * 링크가 아니다: 가이드 예시는 튜토리얼 시드 기준이고 서비스에 올라간 작품은 그 뒤로 고쳐졌을 수 있어, 눌러 들어간
 * 작품이 가이드와 다르면 혼란만 준다. 카드 껍데기 없이 표지와 글을 나란히 둔다. 표지는 첫 화면의 그림이라 지연 로딩하지
 * 않는다.
 */
export function GuideExampleWork({ context }: GuideExampleWorkProps) {
  const name = context.valueOf("profile.name");
  const oneLiner = context.valueOf("profile.oneLiner");
  const coverToken = context.valueOf("profile.image");
  const cover = coverToken ? findGuideImage(coverToken.trim()) : null;
  if (!name || !cover) return null;

  return (
    <figure className="m-0 flex items-start gap-4">
      <div className="aspect-story w-28 shrink-0 overflow-hidden rounded-lg bg-muted">
        <img
          src={cover.src}
          width={cover.width}
          height={cover.height}
          alt={`예시 작품 「${name}」의 표지`}
          decoding="async"
          className="size-full object-cover"
        />
      </div>
      <figcaption className="flex min-w-0 flex-col gap-1.5">
        <span className="text-xs text-muted-foreground">이 가이드의 모든 예시는 이 작품이에요</span>
        <span className="text-lg font-semibold tracking-tight text-balance break-keep text-foreground">{name}</span>
        {oneLiner && <span className="text-sm break-keep text-muted-foreground">{oneLiner}</span>}
      </figcaption>
    </figure>
  );
}
