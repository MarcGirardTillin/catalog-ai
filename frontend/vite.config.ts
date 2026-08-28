import path from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
const enablePolling =
  process.env.CHOKIDAR_USEPOLLING === 'true' || Boolean(process.env.WSL_DISTRO_NAME)

// Identifiant de build : injecté dans le bundle (__BUILD_ID__) ET publié
// dans /version.json — l'app compare les deux périodiquement pour proposer
// de recharger après un déploiement (demande Marc 2026-08-28).
const buildId = Date.now().toString(36)
const versionFile = (): Plugin => ({
  name: 'catalog-version-file',
  generateBundle() {
    this.emitFile({
      type: 'asset',
      fileName: 'version.json',
      source: JSON.stringify({ build: buildId }),
    })
  },
})

export default defineConfig({
  plugins: [tailwindcss(), svelte(), versionFile()],
  define: { __BUILD_ID__: JSON.stringify(buildId) },
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
