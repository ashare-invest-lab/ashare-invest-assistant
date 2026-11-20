/** 只接受查表自身的键；已知键对应的空值也原样保留。 */
export function ownValue<T, F>(map: Readonly<Record<string, T>>, key: PropertyKey, fallback: F): T | F {
  return Object.hasOwn(map, key) ? map[key as string] : fallback;
}

export const UNKNOWN_ENUM = { text: '未知', color: undefined };
