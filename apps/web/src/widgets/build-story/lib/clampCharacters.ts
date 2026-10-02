import { countCharacters } from "@/features/build-story";

/**
 * 글자 수를 서버와 같은 코드 포인트로 잘라, 입력이 상한을 넘는 값을 폼에 만들지 않는다. 잘랐는지도 함께 돌려줘
 * 화면이 "넘친 글자는 넣지 않았어요" 를 그 순간에만 알릴 수 있게 한다(상한에 딱 맞는 입력은 자른 것이 아니다).
 */
export function clampCharacters(value: string, max: number): { value: string; isTruncated: boolean } {
  if (countCharacters(value) <= max) return { value, isTruncated: false };
  return { value: [...value].slice(0, max).join(""), isTruncated: true };
}
