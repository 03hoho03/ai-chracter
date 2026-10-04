import type { AdminContentDetailResponse } from "@/entities/admin-content";

type PublishedImagesSectionProps = {
  images: AdminContentDetailResponse["publishedImages"];
};

/**
 * 발행본의 그림 전부(대표·상황 이미지·미디어 북 칸)를 축소본으로 늘어놓는다. 칸이 50장까지라 원본은 그리지 않고,
 * 누르면 원본(블러 처리 전)을 새 탭에서 연다. 라벨은 발행 심사가 그림을 부르는 이름과 같다.
 */
export function PublishedImagesSection({ images }: PublishedImagesSectionProps) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4 @xl:p-6">
      <h2 className="text-lg font-semibold text-foreground">
        발행본 이미지 <span className="tabular-nums text-muted-foreground">{images.length}</span>
      </h2>
      {images.length === 0 ? (
        <p className="text-sm text-muted-foreground">발행본 이미지가 없어요.</p>
      ) : (
        <ul className="grid grid-cols-3 gap-3 @xl:grid-cols-4">
          {/* 같은 그림이 두 칸에 걸릴 수 있고 인물·장면 이름이 겹칠 수도 있어, 라벨과 주소를 함께 키로 쓴다. */}
          {images.map((image) => (
            <li key={`${image.label}|${image.imageUrl}`}>
              <a
                href={image.imageUrl}
                target="_blank"
                rel="noreferrer"
                className="group flex flex-col gap-1.5 rounded-lg outline-none"
              >
                {/* 포커스 표시는 썸네일 테두리가 진다 — 50% 링만으로는 배경 대비 3:1 에 못 닿는다. */}
                <span className="block aspect-square overflow-hidden rounded-lg border border-border bg-secondary group-focus-visible:border-ring group-focus-visible:ring-3 group-focus-visible:ring-ring/50">
                  <img
                    src={image.thumbnailUrl}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="size-full object-cover"
                  />
                </span>
                <span className="truncate text-xs text-muted-foreground group-hover:text-foreground" title={image.label}>
                  {image.label}
                  <span className="sr-only"> 원본 새 탭에서 열기</span>
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
