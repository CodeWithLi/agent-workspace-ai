import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [
      vue(),
      AutoImport({ resolvers: [ElementPlusResolver()], dts: 'src/auto-imports.d.ts' }),
      Components({ resolvers: [ElementPlusResolver()], dts: 'src/components.d.ts' })
    ],
    server: {
      port: 5173,
      proxy: {
        '/api': env.VITE_API_PROXY || 'http://localhost:8000'
      }
    }
  }
})
