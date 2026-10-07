function clampPoint(x,y,area,w,h) {
  return {x:Math.round(Math.max(area.x,Math.min(x,area.x+area.width-w))),
          y:Math.round(Math.max(area.y,Math.min(y,area.y+area.height-h)))};
}
function panelPosition(m,area,w,h){
  const x=m.x-w-12>=area.x?m.x-w-12:m.x+m.width+12;
  return clampPoint(x,m.y+ m.height-h,area,w,h);
}
module.exports={clampPoint,panelPosition};
