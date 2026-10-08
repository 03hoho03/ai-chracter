/** 받침에 따라 갈리는 조사 쌍. 앞이 받침 있는 말 뒤, 뒤가 받침 없는 말 뒤의 꼴이다. */
const PARTICLE_PAIRS = {
  "을/를": ["을", "를"],
  "이/가": ["이", "가"],
  "은/는": ["은", "는"],
  "과/와": ["과", "와"],
  "으로/로": ["으로", "로"],
} as const;

export type KoreanParticle = keyof typeof PARTICLE_PAIRS;

const HANGUL_FIRST = 0xac00;
const HANGUL_LAST = 0xd7a3;
/** 종성 번호 ㄹ. `으로/로` 는 ㄹ 받침 뒤에 `로` 다. */
const RIEUL_FINAL = 8;

/**
 * 이름·문구 뒤에 붙일 조사. 끝 글자의 받침으로 고른다(`‘15화까지’로`, `‘민재’를`, `‘첫 저장’을`). 사용자가 붙인
 * 이름 뒤에 고정 조사를 쓰면 이름에 따라 틀린다. 끝 글자가 한글 음절이 아니면(`Alex`, `v2`) 받침을 알 수 없어 두
 * 꼴을 함께 적는다(`을(를)`).
 */
export function koreanParticle(word: string, particle: KoreanParticle): string {
  const [withFinal, withoutFinal] = PARTICLE_PAIRS[particle];
  const last = word.trimEnd().codePointAt(word.trimEnd().length - 1);
  if (last === undefined || last < HANGUL_FIRST || last > HANGUL_LAST) return `${withFinal}(${withoutFinal})`;
  const finalIndex = (last - HANGUL_FIRST) % 28;
  if (finalIndex === 0) return withoutFinal;
  if (particle === "으로/로" && finalIndex === RIEUL_FINAL) return withoutFinal;
  return withFinal;
}
