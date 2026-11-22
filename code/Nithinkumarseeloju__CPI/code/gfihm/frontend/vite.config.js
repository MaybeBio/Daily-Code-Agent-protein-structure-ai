import { copyFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const at = path => fileURLToPath(new URL(path, import.meta.url));

// FastAPI serves this build and the existing model APIs on the same origin.
export default defineConfig({
  plugins: [{
    name: 'shared-cpi-page',
    closeBundle() { copyFileSync(at('./index.html'), at('../viewer/cpi.html')); }
  }],
  build: {
    outDir: at('../viewer/experience'),
    emptyOutDir: true,
    lib: { entry: at('./src/main.js'), formats: ['es'], fileName: () => 'experience.js', cssFileName: 'experience' }
  }
});
