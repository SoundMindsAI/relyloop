/**
 * ESLint flat config — migrated from legacy .eslintrc.json on 2026-05-12
 * (see infra_frontend_stack_refresh). ESLint 9 deprecated the legacy
 * .eslintrc.* format; ESLint 10 removed support entirely. The flat config
 * format moves shared rules into composable arrays.
 *
 * eslint-config-next 16 ships flat-config-native exports, so no FlatCompat
 * shim is needed. Mirrors the prior .eslintrc.json: next/core-web-vitals +
 * eslint-plugin-security recommended + the react/no-unescaped-entities
 * override.
 */

import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import securityPlugin from 'eslint-plugin-security';

const config = [
  ...nextCoreWebVitals,
  securityPlugin.configs.recommended,
  {
    rules: {
      'react/no-unescaped-entities': 'off',
    },
  },
];

export default config;
