import type { Config } from 'jest';

import base from './jest.config';

const config: Config = {
  ...base,
  transform: {
    '^.+\\.(ts|tsx|js|jsx)$': [
      'esbuild-jest',
      {
        sourcemap: true,
        loaders: {
          '.ts': 'ts',
          '.tsx': 'tsx',
        },
      },
    ],
  },
  testMatch: ['<rootDir>/src/pages/cs-interview/**/__tests__/*.{ts,tsx}'],
  collectCoverageFrom: [
    'src/pages/cs-interview/**/*.{ts,tsx}',
    'src/services/cs-interview-service.ts',
    'src/hooks/use-cs-interview-request.ts',
    '!**/*.d.ts',
    '!**/__tests__/**',
  ],
  coverageThreshold: {
    global: {
      branches: 10,
      functions: 20,
      lines: 20,
      statements: 20,
    },
  },
};

export default config;
