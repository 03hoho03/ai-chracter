// 서비스 소개 화면이 기능마다 곁들이는 실제 화면 캡처.
//
// public/이 아니라 src 임포트인 이유: public/은 해시 없이 원본 이름 그대로 dist/에 복사되지만,
// src에서 import하면 Vite가 콘텐츠 해시를 붙여 캡처를 다시 뜨면 URL이 저절로 바뀐다.
// width·height는 파일의 실제 픽셀이다 — <img>에 그대로 넘겨 그림이 오기 전에 비율만큼 자리를 잡는다.
//
// ── 촬영 조건 ────────────────────────────────
// 다시 뜰 때 같은 화면이 나오도록 전부 남긴다.
//
//   2026-10-03, 프로덕션 · 뷰포트 390×844 CSS · 기기 배율 2 · 다크 테마
//   대상은 팀이 직접 올린 시드 작품 "복학했더니 영화 동아리 조감독이 됐다"(스토리)와 그 인물 민유나(캐릭터)다.
//   채팅 화면 아래의 입력줄(클로버 잔액이 함께 보이는 줄)과 클로버 화면의 잔액 줄은 잘라 냈다.
//   `cwebp -q 80 -m 6` 으로 WebP 변환. 다섯 장은 780×1440, 클로버 미션은 780×870 이다.
import chatCharacter from "../screenshots/chat_character.webp";
import cloverMissions from "../screenshots/clover_missions.webp";
import contentDetail from "../screenshots/content_detail.webp";
import imageVault from "../screenshots/image_vault.webp";
import storyPlay from "../screenshots/story_play.webp";
import studioVault from "../screenshots/studio_vault.webp";

export type AboutScreenshot = {
  src: string;
  width: number;
  height: number;
  alt: string;
};

export const ABOUT_SCREENSHOTS = {
  chatCharacter: {
    src: chatCharacter,
    width: 780,
    height: 1440,
    alt: "캐릭터 민유나와의 대화 화면 — 첫 장면 서술, 사용자의 대사, 캐릭터의 답장과 장면에 맞춰 나온 그림",
  },
  storyPlay: {
    src: storyPlay,
    width: 780,
    height: 1440,
    alt: "스토리 '복학했더니 영화 동아리 조감독이 됐다' 플레이 화면 — 인물별 호감도 막대, 장소·시간·함께 있는 인물·지금 상황 안내와 장면 그림",
  },
  contentDetail: {
    src: contentDetail,
    width: 780,
    height: 1440,
    alt: "스토리 상세 화면 — 표지 그림과 제목, 플레이 버튼",
  },
  imageVault: {
    src: imageVault,
    width: 780,
    height: 1440,
    alt: "이미지 보관함 — '18장 중 4장을 모았어요' 안내와 모은 장면, 흐리게 잠긴 장면 칸",
  },
  studioVault: {
    src: studioVault,
    width: 780,
    height: 1440,
    alt: "이미지 스튜디오 보관함 — 직접 생성한 캐릭터 이미지들과 '1곳에서 사용 중' 표시",
  },
  cloverMissions: {
    src: cloverMissions,
    width: 780,
    height: 870,
    alt: "클로버 화면 — 출석체크 버튼과 미션 목록(첫 작품 발행 300, 첫 대화 100, 첫 이미지 생성 200)",
  },
} satisfies Record<string, AboutScreenshot>;
