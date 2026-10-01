import { splitMediaTagText, type MediaTagImages } from "@/entities/media-book";
import { MediaImageFrame, type MediaImageSurface } from "@/shared/ui/media-image-frame/MediaImageFrame";

type MediaTagTextProps = {
  text: string;
  images: MediaTagImages;
  /** 글 조각(`<p>`)에 입히는 클래스 — 원래 평문 문단의 클래스를 그대로 준다. */
  className?: string;
  surface: MediaImageSurface;
};

type MediaTagTextImageProps = {
  image: MediaTagImages[string] | undefined;
  surface: MediaImageSurface;
};

/**
 * 상세의 작성자 글(등록 설명·프롤로그)을 평문 그대로 두고 칸 id 형태 태그 자리에만 그림 블록을 세운다. 마크다운으로
 * 바꾸지 않는 이유: 기존 설명이 `*`·`#` 를 글자로 쓰고 있으면 렌더러를 바꾸는 순간 기존 작품의 표시가 달라진다.
 * 맵에 없는 칸의 태그는 빈칸이다. 태그가 없으면 원래와 같은 문단 하나다.
 */
export function MediaTagText({ text, images, className, surface }: MediaTagTextProps) {
  const segments = splitMediaTagText(text, images);
  const [first] = segments;
  if (segments.length <= 1 && first?.kind !== "image") {
    return <p className={className}>{first?.text ?? ""}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {/* 조각은 글에서 매번 같은 순서로 나오는 파생 목록이고 id 가 없어, 순서와 종류로 key 를 만든다. */}
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <p key={`text-${index}`} className={className}>
            {segment.text}
          </p>
        ) : (
          <MediaTagTextImage key={`image-${index}`} image={images[segment.cellId]} surface={surface} />
        ),
      )}
    </div>
  );
}

function MediaTagTextImage({ image, surface }: MediaTagTextImageProps) {
  if (image === undefined) return null;
  return (
    <MediaImageFrame url={image.url} width={image.width} height={image.height} alt="작품 속 그림" surface={surface} />
  );
}
