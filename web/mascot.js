const pet=document.getElementById('pet');let start=null,moved=false;
pet.addEventListener('pointerdown',e=>{start={x:e.screenX,y:e.screenY,dx:e.clientX,dy:e.clientY};moved=false;pet.setPointerCapture(e.pointerId);});
pet.addEventListener('pointermove',e=>{if(!start)return;if(Math.hypot(e.screenX-start.x,e.screenY-start.y)>4)moved=true;if(moved)window.nudge?.drag(e.screenX-start.dx,e.screenY-start.dy);});
pet.addEventListener('pointerup',()=>{if(start&&!moved)window.nudge?.toggle();start=null;});
pet.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();window.nudge?.toggle();}});
pet.addEventListener('contextmenu',e=>{e.preventDefault();window.nudge?.menu();});
window.nudge?.onBadge(n=>{const b=document.getElementById('badge');b.textContent=n;b.style.display=n?'block':'none';});
let reactionTimer,playingAudio=null;
function playSound(sound){
 if(playingAudio){playingAudio.pause();playingAudio.removeAttribute('src');playingAudio.load();playingAudio=null;}
 if(!['woof','howl'].includes(sound)){pet.dataset.soundStatus='silent';return;}
 const source=sound==='woof'?'sounds/wolf-bark.wav':'sounds/howl.wav';pet.dataset.soundSource=source;const audio=new Audio(source);playingAudio=audio;audio.volume=.65;pet.dataset.lastSound=sound;pet.dataset.soundStatus='starting';
 audio.addEventListener('playing',()=>{if(playingAudio!==audio)return;pet.dataset.soundStatus='playing';pet.dataset.playCount=String((Number(pet.dataset.playCount)||0)+1);});
 audio.addEventListener('ended',()=>{if(playingAudio===audio){pet.dataset.soundStatus='ended';playingAudio=null;audio.removeAttribute('src');audio.load();}});
 audio.addEventListener('error',()=>{if(playingAudio===audio)pet.dataset.soundStatus='error';});audio.play().catch(()=>{if(playingAudio===audio)pet.dataset.soundStatus='blocked';});
}
function reactToNotification(event){clearTimeout(reactionTimer);pet.classList.remove('reacting');void pet.offsetWidth;pet.classList.add('reacting');pet.dataset.alertCount=String((Number(pet.dataset.alertCount)||0)+1);reactionTimer=setTimeout(()=>pet.classList.remove('reacting'),1600);playSound(event.sound);}
window.nudge?.onNotification(reactToNotification);window.nudge?.onSoundPreview(event=>playSound(event.sound));
