#!/usr/bin/env python3
"""Allowlisted source archive: no personal state, screenshots, dependencies or secrets."""
import hashlib, json, re, zipfile
from pathlib import Path
root=Path(__file__).resolve().parent.parent
version=json.loads((root/'package.json').read_text())['version']
files=['README.md','README-backend.md','LICENSE','SECURITY.md','CONTRIBUTING.md','.gitignore',
'package.json','package-lock.json','backend.py','main.cjs','preload.cjs','client-core.cjs','shell-utils.cjs',
'test_backend.py','test-shell.cjs','test-client.cjs','test-ui.cjs','verify-desktop.cjs','create-icon.cjs',
'web/index.html','web/app.js','web/styles.css','web/settings.js','web/settings.css',
'web/workflows.js','web/body-links.js','test-main-performance.cjs','test-coaching-todos.cjs','test-workflows.cjs','web/custom-notifications.js','test-custom-notifications.cjs','web/token-controls.css','web/panels.js','test-panels.cjs','test-glass.cjs','test-layout.cjs','test-notification-rules.cjs','test-notification-prefs.cjs','web/notification-rules.js','test-mascot-alerts.cjs','scripts/create_sounds.py','scripts/build_mascot.py','web/sounds/woof.wav','web/sounds/wolf-bark.mp3','web/sounds/wolf-bark.wav','test-fast-open.cjs','test-reflection-errors.cjs','scripts/trim_client.py','web/sounds/howl.wav','verify-token-controls.cjs','verify-memory.cjs','web/mascot.html','web/mascot.js','web/mascot.svg','assets/mascot.png','assets/Nudge.icns',
'.github/workflows/ci.yml','scripts/build_dmg.py','scripts/build_source.py']
files+=sorted(str(p.relative_to(root)) for p in (root/'docs').rglob('*.md'))
for file in files:
 p=root/file
 if not p.is_file(): raise SystemExit('Missing source: '+file)
 if p.suffix not in ('.png','.icns','.wav','.mp3'):
  text=p.read_text()
  if '/'+ 'Users/' in text or re.search(r'192'+r'\.168\.|xox[bap]-|ghp_[A-Za-z0-9]{20}|sk-[A-Za-z0-9]{30}',text):
   raise SystemExit('Personal path or credential pattern in '+file)
out=root/'dist';out.mkdir(exist_ok=True)
archive=out/f'Woof-{version}-source.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for file in files:z.write(root/file,'woof/'+file)
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 assert len(z.namelist())==len(files)
checks=[]
for p in (out/f'Woof-{version}-arm64.dmg',archive):
 if p.exists():
  h=hashlib.sha256()
  with p.open('rb') as stream:
   for block in iter(lambda:stream.read(1048576),b''):h.update(block)
  checks.append(h.hexdigest()+'  '+p.name)
(out/'SHA256SUMS.txt').write_text('\n'.join(checks)+'\n')
print('Verified source archive:',archive,'files:',len(files))
print('\n'.join(checks))
