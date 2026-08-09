import '@testing-library/jest-dom';
import { ReadableStream } from 'node:stream/web';
import { TextDecoder, TextEncoder } from 'node:util';
import React from 'react';

Object.defineProperty(globalThis, 'React', {
  configurable: true,
  value: React,
});

Object.defineProperty(globalThis, 'TextDecoder', {
  configurable: true,
  value: TextDecoder,
});
Object.defineProperty(globalThis, 'TextEncoder', {
  configurable: true,
  value: TextEncoder,
});
Object.defineProperty(globalThis, 'ReadableStream', {
  configurable: true,
  value: ReadableStream,
});
