import { globalIgnores } from 'eslint/config'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'
import pluginVitest from '@vitest/eslint-plugin'
import pluginA11y from 'eslint-plugin-vuejs-accessibility'
import skipFormatting from 'eslint-config-prettier/flat'

export default defineConfigWithVueTs(
  { name: 'app/files-to-lint', files: ['**/*.{vue,ts,mts,tsx}'] },

  globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/coverage/**']),

  ...pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommendedTypeChecked,
  ...pluginA11y.configs['flat/recommended'],
  {
    // Basta con `for`/`id` o con anidar el campo (ambas formas cumplen WCAG).
    name: 'app/a11y-label',
    rules: {
      'vuejs-accessibility/label-has-for': ['error', { required: { some: ['nesting', 'id'] } }],
    },
  },

  {
    ...pluginVitest.configs.recommended,
    files: ['src/**/__tests__/*'],
  },

  // Siempre al final: desactiva reglas que chocan con Prettier
  skipFormatting,
)
