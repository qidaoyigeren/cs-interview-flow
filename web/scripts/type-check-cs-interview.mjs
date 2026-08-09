import path from 'node:path';
import process from 'node:process';
import ts from 'typescript';

const root = process.cwd();
const configPath = ts.findConfigFile(root, ts.sys.fileExists, 'tsconfig.json');
if (!configPath) throw new Error('tsconfig.json not found');

const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(
  configFile.config,
  ts.sys,
  path.dirname(configPath),
);
const program = ts.createProgram(parsed.fileNames, parsed.options);
const owned = [
  `${path.sep}src${path.sep}pages${path.sep}cs-interview${path.sep}`,
  `${path.sep}src${path.sep}services${path.sep}cs-interview-service.ts`,
  `${path.sep}src${path.sep}hooks${path.sep}use-cs-interview-request.ts`,
  `${path.sep}src${path.sep}interfaces${path.sep}database${path.sep}cs-interview.ts`,
  `${path.sep}src${path.sep}interfaces${path.sep}request${path.sep}cs-interview.ts`,
];

const diagnostics = ts
  .getPreEmitDiagnostics(program)
  .filter((diagnostic) =>
    diagnostic.file
      ? owned.some((segment) => diagnostic.file.fileName.includes(segment))
      : false,
  );

if (diagnostics.length) {
  process.stderr.write(
    ts.formatDiagnosticsWithColorAndContext(diagnostics, {
      getCanonicalFileName: (fileName) => fileName,
      getCurrentDirectory: () => root,
      getNewLine: () => ts.sys.newLine,
    }),
  );
  process.exit(1);
}

process.stdout.write('CS interview TypeScript diagnostics: 0\n');
