#!/usr/bin/env python3
"""Trim generated English-only Woof client, never developer/source files.
Keep all English variants, ICU international date/time data, graphics and audio libraries.
"""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parent.parent
resources=root/'dist/Woof-darwin-arm64/Woof.app/Contents/Frameworks/Electron Framework.framework/Versions/A/Resources'
assert (resources/'en.lproj').is_dir(), 'Unexpected Electron layout: refusing to trim'
assert (resources/'icudtl.dat').is_file()
assert (resources.parent/'Libraries/libffmpeg.dylib').is_file()
saved=0;removed=0
for locale in resources.glob('*.lproj'):
 if locale.name.startswith('en') or locale.name=='Base.lproj':continue
 saved+=sum(p.stat().st_size for p in locale.rglob('*') if p.is_file())
 shutil.rmtree(locale);removed+=1
# ponytail: npm's generated install metadata is not used by the packaged runtime.
lock=root/'dist/Woof-darwin-arm64/Woof.app/Contents/Resources/app/node_modules/.package-lock.json'
if lock.is_file():saved+=lock.stat().st_size;lock.unlink()
print('English-only runtime:',removed,'unused locale directories removed;',saved,'bytes removed; ICU/audio/licenses retained')
