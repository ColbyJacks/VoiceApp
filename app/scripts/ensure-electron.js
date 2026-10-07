// Makes sure Electron's binary is unpacked in node_modules/electron/dist.
//
// Electron's own postinstall unzips with extract-zip, which quits silently
// part-way through on Node 24, leaving "Electron failed to install
// correctly". This downloads the same zip with @electron/get and unpacks it
// with Windows' built-in tar instead.

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const electronDir = path.join(__dirname, '..', 'node_modules', 'electron');
const dist = path.join(electronDir, 'dist');
const exe = path.join(dist, process.platform === 'win32' ? 'electron.exe' : 'electron');

async function main() {
  if (fs.existsSync(exe) && fs.existsSync(path.join(electronDir, 'path.txt'))) return;
  const { version } = require(path.join(electronDir, 'package.json'));
  const { downloadArtifact } = require('@electron/get');
  console.log(`Downloading Electron ${version} (first run only)...`);
  const zip = await downloadArtifact({ version, artifactName: 'electron', platform: process.platform, arch: process.arch });
  fs.rmSync(dist, { recursive: true, force: true });
  fs.mkdirSync(dist, { recursive: true });
  execFileSync('tar', ['-xf', zip, '-C', dist], { stdio: 'inherit' });
  fs.writeFileSync(path.join(electronDir, 'path.txt'), path.basename(exe));
  console.log('Electron is ready.');
}

main().catch((err) => {
  console.error(`Couldn't set up Electron: ${err.message}`);
  process.exit(1);
});
