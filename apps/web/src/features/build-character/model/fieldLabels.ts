import { NOVEL_PERMISSION_FIELD_LABEL } from "@/entities/content";

/**
 * 캐릭터 빌더 칸 라벨의 단일 소스. 빌더 탭이 이 값으로 칸 라벨을 그리고, 발행 전 확인 목록도 오류 경로의 칸 이름을 여기서 찾는다
 * (`fieldLabelForPath`) — 두 자리의 칸 이름이 어긋날 수 없게 한다.
 *
 * 키는 폼 경로이고 배열 위치는 `*` 로 쓴다(`CHARACTER_TABS` 의 `fields` 와 같은 표기). 목록 키(`intro.exampleDialogues`)의 라벨은
 * 목록에서 항목 하나를 부르는 이름이기도 하다("2번째 예시 대화 사용자 대사"). 발행 검사가 오류를 낼 수 있는 칸을 모두 담는다.
 */
export const CHARACTER_FIELD_LABELS = {
  "profile.image": { label: "대표 이미지" },
  "profile.name": { label: "이름" },
  "profile.oneLiner": { label: "한줄소개" },

  "intro.firstMessage": { label: "인트로 (첫 대화 본문)" },
  "intro.exampleDialogues": { label: "예시 대화" },
  "intro.exampleDialogues.*.userLine": { label: "사용자 대사" },
  "intro.exampleDialogues.*.characterLine": { label: "캐릭터 대사" },
  "intro.playGuide": { label: "플레이가이드" },

  "prompt.characterPrompt": { label: "캐릭터 프롬프트" },

  situationalImages: { label: "상황별 이미지" },
  "situationalImages.*.situationDescription": { label: "노출할 상황" },

  "registration.description": { label: "등록 설명" },
  "registration.genre": { label: "장르" },
  "registration.target": { label: "타겟" },
  "registration.hashtags": { label: "해시태그" },
  "registration.novelPermission": { label: NOVEL_PERMISSION_FIELD_LABEL },
} as const satisfies Record<string, { label: string }>;
