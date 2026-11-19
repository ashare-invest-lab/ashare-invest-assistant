import type { Rule } from 'antd/es/form';

/** 注册与改密共用的本地规则；弱口令、同用户名由服务端判定。 */
export const PASSWORD_RULES: Rule[] = [
  { min: 10, message: '至少 10 位' },
  { max: 128, message: '不超过 128 位' },
  { pattern: /(?=.*[A-Za-z])(?=.*\d)/, message: '需同时包含字母和数字' },
];
