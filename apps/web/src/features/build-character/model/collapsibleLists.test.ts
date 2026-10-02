import { describe, expect, it } from "vitest";
import { z } from "zod";

import { CHARACTER_COLLAPSIBLE_LISTS } from "./collapsibleLists";
import { characterBuilderSchema } from "./schema";

/** 기본값·선택·null 허용 껍질을 벗겨 안쪽 스키마를 꺼낸다. */
function unwrap(schema: z.core.$ZodType): z.core.$ZodType {
  if (schema instanceof z.ZodDefault || schema instanceof z.ZodOptional || schema instanceof z.ZodNullable) {
    return unwrap(schema.unwrap());
  }
  return schema;
}

/** `instanceof` 만으로는 모양이 `any` 로 좁혀져 키 조회 결과가 타입 검사를 벗어난다. */
function isObjectSchema(schema: z.core.$ZodType): schema is z.ZodObject<z.core.$ZodShape> {
  return schema instanceof z.ZodObject;
}

/** 점 경로를 스키마에서 따라가 끝이 배열인지 본다. `*` 는 배열 항목 자리라 그 배열의 항목 스키마로 내려간다. */
function isArrayPath(schema: z.core.$ZodType, path: string): boolean {
  let current = unwrap(schema);
  for (const segment of path.split(".")) {
    if (segment === "*") {
      if (!(current instanceof z.ZodArray)) return false;
      current = unwrap(current.element);
    } else {
      if (!isObjectSchema(current)) return false;
      const next = current.shape[segment];
      if (!next) return false;
      current = unwrap(next);
    }
  }
  return current instanceof z.ZodArray;
}

// 경로가 틀리면 발행 실패 때 그 목록만 조용히 안 열린다. 타입은 경로 문자열의 뜻을 모르니 스키마와 직접 대조한다.
describe("CHARACTER_COLLAPSIBLE_LISTS", () => {
  it.each(Object.entries(CHARACTER_COLLAPSIBLE_LISTS))("%s 의 path 가 폼 스키마의 배열 필드를 가리킨다", (_, list) => {
    expect(isArrayPath(characterBuilderSchema, list.path)).toBe(true);
  });
});
