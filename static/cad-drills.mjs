// Coordinates in source millimetres. Slots already have global endpoints.
export function capsuleContour(start, end, diameter, segments = 32) {
  if (!(diameter > 0) || ![...start, ...end].every(Number.isFinite)) throw new Error('Invalid drill geometry');
  const angle = Math.atan2(end[1]-start[1], end[0]-start[0]);
  const radius = diameter/2, points = [];
  for (const [center, offset] of [[end, -Math.PI/2], [start, Math.PI/2]]) {
    for (let i=0; i<=segments; i++) {
      const a = angle+offset+i*Math.PI/segments;
      points.push([center[0]+radius*Math.cos(a), center[1]+radius*Math.sin(a)]);
    }
  }
  return points;
}
export function drillContour(drill) {
  const diameter = Number(drill.drill ?? drill.diameter);
  if (!(diameter > 0)) return [];
  const points = drill.slotPointsMM;
  if (drill.slotLength && (!Array.isArray(points) || points.length !== 2)) throw new Error('Missing slot centerline');
  return capsuleContour(points?.[0] ?? [drill.x, drill.y], points?.[1] ?? [drill.x, drill.y], diameter);
}
export function padContours(pad) {
  const w=Number(pad.width), h=Number(pad.height), shape=String(pad.shape).toUpperCase();
  let outer;
  if (shape === 'RECT') outer=[[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]];
  else if (shape === 'OVAL') outer=w>=h ? capsuleContour([-(w-h)/2,0],[(w-h)/2,0],h) : capsuleContour([0,-(h-w)/2],[0,(h-w)/2],w);
  else if (shape === 'ELLIPSE') outer=Array.from({length:64},(_,i)=>[w/2*Math.cos(i*Math.PI/32),h/2*Math.sin(i*Math.PI/32)]);
  else throw new Error(`Unsupported pad shape: ${shape}`);
  const angle=-Number(pad.rotation || 0)*Math.PI/180, c=Math.cos(angle), s=Math.sin(angle);
  const hole=drillContour(pad).map(([x,y])=>{
    const dx=x-pad.x,dy=y-pad.y;
    return [c*dx-s*dy,s*dx+c*dy];
  });
  return {outer,hole};
}
