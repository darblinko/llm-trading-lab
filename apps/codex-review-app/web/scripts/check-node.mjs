const major = Number(process.versions.node.split('.')[0]);

if (major !== 24) {
  console.error(
    `Codex Review App requires Node 24 LTS; this process is using ${process.version}.\n` +
    'Run `nvm use` inside codex-review-app (or its web directory), then retry.\n' +
    'If Node 24 is installed but not selected, load NVM in this shell first.',
  );
  process.exitCode = 1;
}
