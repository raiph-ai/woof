#!/usr/bin/env python3
"""Build and verify an Apple-silicon DMG from the packaged app (macOS only)."""
import json, os, shutil, subprocess, tempfile
from pathlib import Path
root=Path(__file__).resolve().parent.parent
version=json.loads((root/'package.json').read_text())['version']
app=root/'dist'/'Woof-darwin-arm64'/'Woof.app'
if not app.is_dir(): raise SystemExit('Run npm run package first.')
output=root/'dist'/f'Woof-{version}-arm64.dmg'
with tempfile.TemporaryDirectory(prefix='hermes-nudge-dmg-',dir=os.environ.get('TMPDIR')) as temp:
 stage=Path(temp)/'installer';stage.mkdir()
 subprocess.run(['ditto',str(app),str(stage/app.name)],check=True)
 (stage/'Applications').symlink_to('/Applications')
 (stage/'START-HERE.txt').write_text('Quit Hermes Nudge before upgrading. Drag Woof to Applications. Pairing/preferences carry over. Launch and enter your bridge URL and pairing token. See README.md for SSH tunnel/HTTPS server setup. This initial build is ad-hoc signed, not notarized.\n')
 shutil.copy2(root/'README.md',stage/'README.md')
 subprocess.run(['hdiutil','create','-volname','Woof','-srcfolder',str(stage),'-format','UDZO','-ov',str(output)],check=True)
subprocess.run(['hdiutil','verify',str(output)],check=True)
print(output)
