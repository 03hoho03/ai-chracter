// 서버(`works/schemas.py`·`works/bundles.py`)가 권위인 값의 사본 — 화면 문구와 입력 검사에만 쓴다. 서버 값을 바꾸면 같이 바꾼다.

/** 묶음 이름 상한(앞뒤 공백을 걷은 뒤 코드 포인트 수). */
export const WORK_BUNDLE_NAME_MAX_LENGTH = 40;
/** 한 사람이 가질 수 있는 묶음 수. */
export const WORK_BUNDLE_MAX_COUNT = 50;
/** 한 묶음에 넣을 수 있는 작품 수. */
export const WORK_BUNDLE_MAX_ITEMS = 500;
