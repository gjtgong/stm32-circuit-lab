const test=require('node:test'), assert=require('node:assert/strict');
const geometry=import('../static/cad-drills.mjs');
const extent=(p,k)=>[Math.min(...p.map(v=>v[k])),Math.max(...p.map(v=>v[k]))];
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,`${a} != ${b}`);
test('global slot endpoints stay fixed despite pad rotation',async()=>{
  const {drillContour,padContours}=await geometry;
  const pad={x:10,y:20,width:1.1,height:2.4,shape:'OVAL',rotation:180,drill:.6,slotLength:1.8,slotPointsMM:[[10,19.4],[10,20.6]]};
  const contour=drillContour(pad);
  extent(contour,0).forEach((v,i)=>near(v,[9.7,10.3][i]));
  extent(contour,1).forEach((v,i)=>near(v,[19.1,20.9][i]));
  const {hole}=padContours(pad);
  const angle=pad.rotation*Math.PI/180;
  hole.forEach(([x,y],i)=>{near(x*Math.cos(angle)-y*Math.sin(angle)+pad.x,contour[i][0]);near(x*Math.sin(angle)+y*Math.cos(angle)+pad.y,contour[i][1]);});
});
test('oval pad and noncircular ellipse retain dimensions',async()=>{
  const {padContours}=await geometry;
  for(const shape of ['OVAL','ELLIPSE','RECT']){
    const {outer,hole}=padContours({x:0,y:0,width:1,height:3,shape,drill:.3});
    extent(outer,0).forEach((v,i)=>near(v,[-.5,.5][i]));
    extent(outer,1).forEach((v,i)=>near(v,[-1.5,1.5][i]));
    assert.ok(hole.length>32);
  }
});
test('missing slot geometry cannot silently become round hole',async()=>{
  const {drillContour}=await geometry;
  assert.throws(()=>drillContour({x:0,y:0,drill:.6,slotLength:1.8}),/slot/);
});
