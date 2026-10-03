import storyCover from "../assets/story-cover.webp";

/**
 * 원고의 이미지 칸 값(`value profile.image free` 의 본문)이 가리키는 그림. 원고는 키 이름만 쓰고 파일은 여기서 고른다 —
 * 원고에 경로를 쓰면 번들러가 해시를 붙인 실제 주소를 원고가 알 수 없다.
 *
 * `public/` 이 아니라 `src` 에서 import 하는 이유: 번들러가 내용 해시를 붙여 그림을 바꾸면 주소도 바뀐다. `public/` 은 같은
 * 주소라 바꾼 뒤 캐시 수명 동안 옛 그림이 보일 수 있다.
 *
 * 만든 조건(다시 만들 때 같은 결과가 나오게 남긴다):
 * - `storyCover` — 예시 작품 「복학했더니 영화 동아리 조감독이 됐다」 표지. 서비스에 올라간 원본(683×1024 webp, 제목 글자
 *   포함)을 `cwebp -q 80 -resize 336 0`(cwebp 1.6.0)으로 336×504, 32,016바이트. 목업의 표지 자리(가로 112px)를 3배 밀도로
 *   채우는 크기다. cwebp 기본값이라 원본의 색 프로필 조각은 남지 않는다.
 */
export const GUIDE_IMAGES = {
  storyCover: { src: storyCover, width: 336, height: 504 },
} as const;

export type GuideImageToken = keyof typeof GUIDE_IMAGES;

/** 그림 없이 자리만 그리는 이미지 칸 값. */
export const GUIDE_IMAGE_PLACEHOLDER = "placeholder";
