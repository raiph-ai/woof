#!/usr/bin/env python3
"""Keep the inline animated mascot and the static SVG/icon source in sync."""
from pathlib import Path
root=Path(__file__).resolve().parent.parent
svg=(root/'web/mascot.svg').read_text()
css='''html,body{margin:0;width:64px;height:72px;overflow:hidden;background:transparent;user-select:none}button{border:0;background:transparent;padding:0;width:64px;height:72px;cursor:grab;position:relative}button:active{cursor:grabbing}button:focus-visible{outline:2px solid #c3cbd6;outline-offset:-5px;border-radius:30px}svg{width:62px;height:65px;pointer-events:none;filter:drop-shadow(0px 3px 4px #27344044)}#badge{position:absolute;right:3px;top:6px;border:2px solid #38434f;background:#ffcc9c;color:#26303b;border-radius:12px;font:700 10px system-ui;min-width:16px;padding:2px;display:none;pointer-events:none;z-index:2}#tail{transform-origin:69px 76px;transform-box:view-box}#pet.reacting #tail{animation:wag .18s ease-in-out 8 alternate}#pet.reacting #mouth-closed{visibility:hidden}#pet.reacting #mouth-open{display:block}@keyframes wag{from{transform:rotate(-18deg)}to{transform:rotate(18deg)}}@media(prefers-reduced-motion:reduce){#pet.reacting #tail{animation:none}}'''
html='''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; img-src 'self' data:; media-src 'self'"><style>'''+css+'''</style></head><body><button id="pet" aria-label="Open Woof notifications" title="Woof · click to open, drag to move">'''+svg+'''<span id="badge" aria-label="Unread notifications"></span></button><script src="mascot.js"></script></body></html>'''
(root/'web/mascot.html').write_text(html)
print('Animated mascot HTML generated from approved SVG')
