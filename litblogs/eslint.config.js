import js from '@eslint/js'
import globals from 'globals'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default [
  { ignores: ['dist', 'eslint.config.js'] },
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^React$' }],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'ExpressionStatement > CallExpression[callee.name="useState"]',
          message: 'Do not discard the value returned by useState.',
        },
        {
          selector: 'ExpressionStatement > CallExpression[callee.name="useRef"]',
          message: 'Do not discard the value returned by useRef.',
        },
        {
          selector: 'ExpressionStatement > CallExpression[callee.name="useNavigate"]',
          message: 'Do not discard the value returned by useNavigate.',
        },
        {
          selector: 'ExpressionStatement > CallExpression[callee.name="useGoogleLogin"]',
          message: 'Do not discard the login callback returned by useGoogleLogin.',
        },
      ],
      'react/jsx-no-target-blank': 'off',
      'react/jsx-uses-vars': 'error',
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  },
]
