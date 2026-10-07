#!/usr/bin/env python3
"""Original, short stylized canine notification effects. No external samples/licensing.
Model: additive/formant synthesis; seed 19; PCM16 mono 24000 Hz.
Woof: two soft, breathy voiced pulses. Howl: a short rising/falling harmonic call.
"""
import math, random, struct, wave
from pathlib import Path
SR=24000
root=Path(__file__).resolve().parent.parent/'web'/'sounds'
root.mkdir(parents=True,exist_ok=True)
for name,duration in [('woof',0.62),('howl',1.18)]:
 rng=random.Random(19);samples=[];phase=0.;noise=0.
 for i in range(int(SR*duration)):
  t=i/SR
  if name=='woof':
   start=0.04 if t<0.28 else 0.31
   u=(t-start)/0.22
   if not 0<u<1:samples.append(0.);continue
   envelope=math.sin(math.pi*u)**1.35
   frequency=290-135*u+12*math.sin(2*math.pi*35*t)
   phase+=2*math.pi*frequency/SR
   voiced=sum((0.35/k+0.45*math.exp(-((k*frequency-1050)/430)**2)+0.22*math.exp(-((k*frequency-1950)/600)**2))*math.sin(k*phase) for k in range(1,13))
   noise=.55*noise+.45*rng.uniform(-1,1)
   value=envelope*(voiced*.18+noise*.18)
  else:
   u=t/duration;envelope=math.sin(math.pi*u)**1.4
   frequency=355+190*math.sin(math.pi*u)**.7+7*math.sin(2*math.pi*6*t)
   phase+=2*math.pi*frequency/SR
   value=envelope*(.50*math.sin(phase)+.12*math.sin(2*phase)+.045*math.sin(3*phase))
  samples.append(value)
 peak=max(abs(v) for v in samples);gain=.45/peak
 with wave.open(str(root/(name+'.wav')),'wb') as out:
  out.setnchannels(1);out.setsampwidth(2);out.setframerate(SR)
  out.writeframes(b''.join(struct.pack('<h',int(max(-1,min(1,v*gain))*32767)) for v in samples))
 with wave.open(str(root/(name+'.wav')),'rb') as check:
  assert check.getnframes()==int(SR*duration) and check.getnchannels()==1
 print(name,'PCM16 mono',SR,'Hz',duration,'seconds',root/(name+'.wav'))
