/**
 * 파일 이름으로 한꺼번에 넣을 때 이미 그림이 있는 칸을 덮어쓸지(`overwrite`) 건너뛸지(`skip`). 묻는 모달과 그 답을
 * 받아 계획을 확정하는 함수가 서로 다른 feature 에 있어, 둘이 같은 선택지를 보도록 여기 한 번만 둔다.
 */
export type OverwriteChoice = "overwrite" | "skip";
