import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/api/client.ts', 'src/components/MarkdownRenderer.vue', 'src/utils/collection.ts', 'src/utils/sse.ts']
    },
    server: { deps: { inline: ['element-plus'] } }
  }
})
