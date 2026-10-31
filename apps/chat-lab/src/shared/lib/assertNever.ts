/** 유니온 분기의 마지막 갈래. 유니온에 새 멤버가 생기면 이 호출이 컴파일을 막아 빠진 분기를 알린다. */
export function assertNever(value: never): never {
  throw new Error(`처리하지 않은 갈래: ${JSON.stringify(value)}`);
}
