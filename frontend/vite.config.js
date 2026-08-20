import {defineConfig, loadEnv} from 'vite'
import path from 'path'
import fs from 'node:fs'
import react from '@vitejs/plugin-react'

const sigmaRuntimeAssets = () => ({
    name: 'sigma-runtime-assets',
    apply: 'build',
    buildStart() {
        const assets = {
            'graph-assets/sigma.min.js': 'node_modules/sigma/dist/sigma.min.js',
            'graph-assets/graphology.umd.min.js': 'node_modules/graphology/dist/graphology.umd.min.js',
        }
        Object.entries(assets).forEach(([fileName, sourcePath]) => {
            this.emitFile({type: 'asset', fileName, source: fs.readFileSync(path.resolve(sourcePath))})
        })
    },
})

// https://vite.dev/config/
export default defineConfig(({mode, command}) => {
    const env = loadEnv(mode, process.cwd());
    return {
        plugins: [react(), sigmaRuntimeAssets()],
        server: {
            open: false,
            port: 8080,
            proxy: {
                '/api': {
                    target: 'http://127.0.0.1:8000',
                    changeOrigin: true,
                    rewrite: (path) => path.replace(/^\/api/, '')
                }
            }
        },
        resolve: {
            alias: {
                "@": path.resolve(__dirname, "./src")
            }
        }
    }
})
