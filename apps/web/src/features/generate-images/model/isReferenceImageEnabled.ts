/** 참조 행을 보일지, 폼에 남은 참조를 보낼지를 정하는 한 판정. 서버는 `supportsReferenceImage`를
 * 모델마다 주므로 **고른 모델**의 값을 본다. 목록이 아직 없거나 고른 모델을 못 찾으면 끈다(값이
 * 없는 옛 서버 응답도 여기서 꺼진다).
 *
 * 인자를 판정에 쓰는 두 필드만 가진 모양으로 받는 이유: 생성 타입의 모델 id가 지금 `"v1"` 하나뿐인
 * 상수라, 모델이 둘인 경우를 테스트로 만들 수가 없다. */
export function isReferenceImageEnabled(
  models: readonly { id: string; supportsReferenceImage: boolean }[] | undefined,
  modelId: string | undefined,
): boolean {
  return models?.find((model) => model.id === modelId)?.supportsReferenceImage === true;
}
