import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    tailwindcss(),
    react({
      // Babel plugins for optimization
      babel: {
        plugins: [
          // Add any babel plugins if needed
        ],
      },
    }),
  ],

  // Path aliases
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@components': path.resolve(__dirname, './src/components'),
      '@pages': path.resolve(__dirname, './src/pages'),
      '@services': path.resolve(__dirname, './src/services'),
      '@hooks': path.resolve(__dirname, './src/hooks'),
      '@types': path.resolve(__dirname, './src/types'),
      '@styles': path.resolve(__dirname, './src/styles'),
      '@utils': path.resolve(__dirname, './src/utils'),
    },
  },

  // Development server configuration
  server: {
    port: 5173,
    host: true, // Listen on all addresses (0.0.0.0)
    strictPort: true, // Exit if port is already in use
    open: false, // Don't auto-open browser
    cors: true, // Enable CORS

    // Proxy API requests to backend
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path, // Keep /api prefix
      },
    },

    // HMR configuration
    hmr: {
      overlay: true, // Show error overlay
    },

    // Watch options
    watch: {
      usePolling: false, // Use native file system events (faster)
      interval: 100, // Polling interval if usePolling is true
    },
  },

  // Preview server configuration (for production builds)
  preview: {
    port: 4173,
    host: true,
    strictPort: true,
    open: false,
    cors: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
      },
    },
  },

  // Build configuration
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: true, // Generate source maps for debugging
    minify: 'esbuild', // Use esbuild for faster minification
    target: 'es2022', // Target modern browsers
    cssCodeSplit: true, // Split CSS into separate files

    // Chunk size warning limit (in KB)
    chunkSizeWarningLimit: 1000,

    // Rollup options for advanced bundling
    rollupOptions: {
      output: {
        // Manual chunk splitting for better caching
        manualChunks: {
          // Vendor chunks for better caching
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'redux-vendor': ['@reduxjs/toolkit', 'react-redux'],
          'chart-vendor': ['recharts'],
          'date-vendor': ['date-fns'],
          'ui-vendor': ['lucide-react', 'clsx'],
        },

        // Asset file naming patterns
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          // Organize assets by type
          const fileName = assetInfo.names?.[0] || '';
          const info = fileName.split('.');
          const ext = info[info.length - 1];

          if (/png|jpe?g|svg|gif|tiff|bmp|ico/i.test(ext)) {
            return 'assets/images/[name]-[hash][extname]';
          }
          if (/woff2?|eot|ttf|otf/i.test(ext)) {
            return 'assets/fonts/[name]-[hash][extname]';
          }
          if (/css/i.test(ext)) {
            return 'assets/css/[name]-[hash][extname]';
          }
          return 'assets/[name]-[hash][extname]';
        },
      },

      // External dependencies (if any need to be excluded)
      external: [],
    },

    // Optimize dependencies
    commonjsOptions: {
      include: [/node_modules/],
      transformMixedEsModules: true,
    },

    // Terser options (if using terser instead of esbuild)
    // terserOptions: {
    //   compress: {
    //     drop_console: true, // Remove console.log in production
    //     drop_debugger: true,
    //   },
    // },
  },

  // CSS configuration
  css: {
    devSourcemap: true, // Enable CSS source maps in dev
    preprocessorOptions: {
      scss: {
        // Silence @import deprecation warnings while migrating to @use/@forward.
        // @import is deprecated in Dart Sass but still works; remove this option
        // once the SCSS partials are migrated to @use/@forward.
        silenceDeprecations: ['import'],
        // Additional SCSS options
        additionalData: ``, // Add global SCSS imports if needed
      },
    },
    modules: {
      // CSS Modules configuration
      localsConvention: 'camelCase',
      scopeBehaviour: 'local',
    },
  },

  // Dependency optimization
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      '@reduxjs/toolkit',
      'react-redux',
      'recharts',
      'date-fns',
      'lucide-react',
      'clsx',
    ],
    exclude: [], // Dependencies to exclude from optimization
    esbuildOptions: {
      target: 'es2022',
    },
  },

  // Environment variables
  envPrefix: 'VITE_', // Only expose env vars starting with VITE_

  // Performance
  esbuild: {
    logOverride: { 'this-is-undefined-in-esm': 'silent' },
    legalComments: 'none', // Remove legal comments
    target: 'es2022',
  },

  // JSON handling
  json: {
    namedExports: true,
    stringify: false,
  },
});
