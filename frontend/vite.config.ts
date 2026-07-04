import path from 'node:path'
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
const enablePolling =
  process.env.CHOKIDAR_USEPOLLING === 'true' || Boolean(process.env.WSL_DISTRO_NAME)

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    watch: {
      usePolling: enablePolling,
      interval: enablePolling ? 120 : undefined,
    },
  },
})
