// 정규화 입력 표 — 서버 테스트 `apps/api/tests/test_media_tags.py` 의 `test_normalize_media_tags` 행을 그대로 옮긴 것이다.
// 빌더 미리보기의 첫 메시지는 FE 구현으로, 실채팅의 첫 메시지는 서버 구현으로 정규화되므로 같은 표로 양쪽을 시험한다.
// 서버 표에 행을 더하면 여기에도 더한다. 테스트만 이 파일을 읽는다.
import type { MediaTagCell } from "./mediaTags";

export const MINA_CLASSROOM = "aaaaaaaa-0000-0000-0000-000000000001";
export const MINA_ROOFTOP = "aaaaaaaa-0000-0000-0000-000000000002";
export const UNKNOWN = "bbbbbbbb-0000-0000-0000-000000000009";

export const CELLS: MediaTagCell[] = [
  { person: "민아", scene: "교실", cellId: MINA_CLASSROOM },
  { person: "민아", scene: "옥상", cellId: MINA_ROOFTOP },
];

const tag = (cellId: string) => `{{img::${cellId}}}`;

/** [행 이름, 입력, 기대 글, 기대 칸 id 목록] */
export const NORMALIZE_CASES: [string, string, string, string[]][] = [
  ["name-form", "{{img::민아/교실}}", tag(MINA_CLASSROOM), [MINA_CLASSROOM]],
  [
    "two-tags-in-a-line",
    "앞 {{img::민아/교실}} 뒤 {{img::민아/옥상}}",
    `앞 ${tag(MINA_CLASSROOM)} 뒤 ${tag(MINA_ROOFTOP)}`,
    [MINA_CLASSROOM, MINA_ROOFTOP],
  ],
  ["spaces-around-names", "{{img:: 민아 / 교실 }}", tag(MINA_CLASSROOM), [MINA_CLASSROOM]],
  ["nfd-names", `{{img::${"민아/교실".normalize("NFD")}}}`, tag(MINA_CLASSROOM), [MINA_CLASSROOM]],
  ["unknown-person-deleted", "앞 {{img::수아/교실}} 뒤", "앞  뒤", []],
  ["unknown-scene-deleted", "앞 {{img::민아/복도}} 뒤", "앞  뒤", []],
  ["known-id-form-kept", tag(MINA_ROOFTOP), tag(MINA_ROOFTOP), [MINA_ROOFTOP]],
  ["upper-case-id-form-canonicalised", tag(MINA_ROOFTOP.toUpperCase()), tag(MINA_ROOFTOP), [MINA_ROOFTOP]],
  ["unknown-id-form-deleted", `앞 ${tag(UNKNOWN)} 뒤`, "앞  뒤", []],
  ["empty-person-deleted", "앞 {{img::/교실}} 뒤", "앞  뒤", []],
  ["empty-scene-deleted", "앞 {{img::민아/}} 뒤", "앞  뒤", []],
  ["both-names-blank-deleted", "앞 {{img:: / }} 뒤", "앞  뒤", []],
  ["no-slash-is-not-a-tag", "{{img::민아}}", "{{img::민아}}", []],
  ["two-slashes-is-not-a-tag", "{{img::민아/교실/밤}}", "{{img::민아/교실/밤}}", []],
  ["half-tag-is-not-a-tag", "{{img::민아/교실", "{{img::민아/교실", []],
  ["empty-body-is-not-a-tag", "{{img::}}", "{{img::}}", []],
  ["other-braces-untouched", "{{user}}와 {{char}}", "{{user}}와 {{char}}", []],
];
