# ruff: noqa: E501
from __future__ import annotations

import argparse
import base64
import json
import math
import socket
import threading
import time
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .robotd import RobotdClient

DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MicroDuck command center</title><style>
.map-canvas{display:block;width:100%;height:auto;aspect-ratio:1;background:#0b1015;image-rendering:pixelated}.map-meta{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0 0}
:root{color-scheme:dark;font:14px system-ui,sans-serif}body{margin:0;background:#10151b;color:#e8edf2}main{max-width:1200px;margin:auto;padding:20px}h1{font-size:22px;margin:0 0 4px}p{color:#aab6c2}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.card{background:#19212a;border:1px solid #30404e;border-radius:8px;padding:14px}.video{grid-column:span 2}h2{font-size:15px;margin:0 0 12px;color:#72d6c9}.camera{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:#050708}.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{background:#111820;padding:8px}.metric b{display:block;font-size:18px}.metric small{color:#93a3b1}.joints{display:grid;grid-template-columns:1fr 1fr;gap:5px}.joint{display:flex;justify-content:space-between;background:#111820;padding:5px 7px}.tof{display:grid;grid-template-columns:repeat(8,1fr);gap:3px}.zone{aspect-ratio:1;display:grid;place-items:center;font-size:10px;color:#061014;border-radius:2px}.muted{color:#aab6c2}.ok{color:#72d6c9}.warning{color:#f4bf68}code{color:#b9d9ff}.controls{display:flex;flex-wrap:wrap;gap:7px;margin:8px 0}.controls button,.controls select{min-height:36px;border:1px solid #496171;background:#111820;color:#e8edf2;padding:7px 10px;border-radius:4px}.controls button:active,.controls button.active{background:#28776d}.danger{border-color:#a85d5d!important}.action-list{width:100%;border-collapse:collapse}.action-list td{padding:5px;border-bottom:1px solid #30404e}.action-list td:first-child{color:#72d6c9;white-space:nowrap}.wide{grid-column:1/-1}@media(max-width:700px){.video{grid-column:span 1}.wide{grid-column:span 1}}
</style></head><body><main><h1>MicroDuck command center</h1><p id="updated">Connecting...</p><section class="grid"><article class="card video"><h2>Camera input</h2><img class="camera" src="/api/camera/stream" alt="MicroDuck head camera stream"></article><article class="card"><h2>Scene semantics</h2><div id="scene" class="metrics"></div><p id="scene-summary" class="muted"></p></article><article class="card"><h2>Autonomous persona</h2><div id="persona" class="metrics"></div><p id="persona-utterance" class="muted"></p></article><article class="card wide"><h2>Command center</h2><div class="controls"><button id="manual">Manual control</button><button id="resume">Resume persona</button><button id="gamepad">Enable browser gamepad</button><button id="stop" class="danger">Stop</button></div><p id="control-status" class="muted">Persona owns the robot.</p><div class="controls"><button data-move='{"vx":0.2,"vy":0,"vyaw":0}'>Forward</button><button data-move='{"vx":-0.2,"vy":0,"vyaw":0}'>Back</button><button data-move='{"vx":0,"vy":0.2,"vyaw":0}'>Left</button><button data-move='{"vx":0,"vy":-0.2,"vyaw":0}'>Right</button><button data-move='{"vx":0,"vy":0,"vyaw":0.5}'>Turn left</button><button data-move='{"vx":0,"vy":0,"vyaw":-0.5}'>Turn right</button><button data-look='{"x":0.5,"y":0.3,"z":0}'>Look left</button><button data-look='{"x":0.5,"y":0,"z":0}'>Look center</button><button data-look='{"x":0.5,"y":-0.3,"z":0}'>Look right</button></div><div class="controls"><button data-action="enable_toggle">Enable / disable</button><button data-action="init">Stand up</button><button data-skill="sit_toggle">Sit / stand</button><button data-skill="ground_pick">Ground pick</button><button data-skill="kick_left">Kick left</button><button data-skill="kick_right">Kick right</button><button data-skill="roulade">Roulade</button><button data-action="relax" class="danger">Relax</button><button data-action="shutdown" class="danger">Shut down</button></div><div class="controls"><select id="sound"><option>chirp</option><option>greet</option><option>inquire</option><option>alarm</option><option>peck</option><option>coo</option></select><button id="sound-play">Play sound</button><button data-mode="walk">Walk mode</button><button data-mode="roller">Roller mode</button><button data-theremin="true">Theremin on</button><button data-theremin="false">Theremin off</button><button data-chorale="true">Chorale on</button><button data-chorale="false">Chorale off</button></div></article><article class="card wide"><h2>Available actions and controller mapping</h2><table class="action-list"><tr><td>Left stick</td><td>Drive forward/back and strafe</td></tr><tr><td>Right stick X</td><td>Turn; in Head mode it rolls the head</td></tr><tr><td>Start</td><td>Toggle policy</td></tr><tr><td>Y</td><td>Toggle Head mode</td></tr><tr><td>B</td><td>Toggle Body-pose mode</td></tr><tr><td>A</td><td>Ground pick</td></tr><tr><td>X</td><td>Roulade; hold to chain</td></tr><tr><td>LB / RB</td><td>Left / right kick</td></tr><tr><td>D-pad Down</td><td>Sit / stand</td></tr><tr><td>D-pad Up, hold 3 s</td><td>Walk / roller mode</td></tr><tr><td>RT / LT</td><td>Mouth + chirp / wheee</td></tr><tr><td>Back, hold 2 s</td><td>Sit and shut down</td></tr><tr><td>Right stick click</td><td>Push-to-talk (project addition)</td></tr><tr><td>D-pad Left / Right</td><td>Unassigned</td></tr><tr><td>Left stick click</td><td>Unassigned</td></tr><tr><td>Command center only</td><td>Look target, stand, relax, stop, individual sounds, theremin, chorale</td></tr></table></article><article class="card"><h2>Robot state</h2><div id="metrics" class="metrics"></div></article><article class="card"><h2>IMU</h2><div id="imu" class="metrics"></div></article><article class="card"><h2>Joints</h2><div id="joints" class="joints"></div></article><article class="card"><h2>ToF / lidar 8×8</h2><div id="tof" class="tof"></div></article></section></main><script>
const commandPanel=[...document.querySelectorAll('article')].find(panel=>panel.querySelector('h2')?.textContent==='Command center');const mapPanel=document.createElement('article');mapPanel.className='card wide';mapPanel.innerHTML='<h2>Persistent occupancy map</h2><canvas id="map" class="map-canvas" width="800" height="800" aria-label="Occupancy map and estimated MicroDuck pose"></canvas><p id="map-meta" class="map-meta muted">Waiting for mapping data...</p>';commandPanel.before(mapPanel);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metric=(name,value,unit='')=>`<div class="metric"><small>${esc(name)}</small><b>${esc(value)} <small>${esc(unit)}</small></b></div>`;
async function checked(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.error||`HTTP ${response.status}`)}return response.json()}
async function post(path,value={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||`HTTP ${response.status}`);return body}
async function refreshMapFullGridLegacy(){try{const map=await checked('/api/map'),canvas=document.querySelector('#map'),ctx=canvas.getContext('2d'),pixels=ctx.createImageData(map.width,map.height);for(let i=0;i<map.cells.length;i++){const value=map.cells[i],color=value===100?[226,94,78]:value===0?[202,214,218]:[22,31,39],row=Math.floor(i/map.width),target=(map.height-1-row)*map.width+(i%map.width),offset=target*4;pixels.data[offset]=color[0];pixels.data[offset+1]=color[1];pixels.data[offset+2]=color[2];pixels.data[offset+3]=255}const layer=document.createElement('canvas');layer.width=map.width;layer.height=map.height;layer.getContext('2d').putImageData(pixels,0,0);ctx.imageSmoothingEnabled=false;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(layer,0,0,canvas.width,canvas.height);const pose=map.localization?.pose;if(pose){const x=(pose.x_m-map.origin_x_m)/map.resolution_m/map.width*canvas.width,y=canvas.height-(pose.y_m-map.origin_y_m)/map.resolution_m/map.height*canvas.height,angle=-pose.yaw_rad;ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.fillStyle='#72d6c9';ctx.strokeStyle='#07110f';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(18,0);ctx.lineTo(-11,-10);ctx.lineTo(-6,0);ctx.lineTo(-11,10);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore()}document.querySelector('#map-meta').textContent=`revision ${map.revision} · coverage ${map.coverage_percent.toFixed(1)}% · ${map.localization?.pose_source||'unlocalized'}${pose?` · x ${pose.x_m.toFixed(2)} m · y ${pose.y_m.toFixed(2)} m`:''}`}catch(error){document.querySelector('#map-meta').textContent='Map unavailable: '+error}}
async function refreshMap(){try{const map=await checked('/api/map'),canvas=document.querySelector('#map'),ctx=canvas.getContext('2d'),pixels=ctx.createImageData(map.width,map.height);for(let i=0;i<map.cells.length;i++){const value=map.cells[i],color=value===100?[226,94,78]:value===0?[202,214,218]:[22,31,39],row=Math.floor(i/map.width),target=(map.height-1-row)*map.width+(i%map.width),offset=target*4;pixels.data[offset]=color[0];pixels.data[offset+1]=color[1];pixels.data[offset+2]=color[2];pixels.data[offset+3]=255}const layer=document.createElement('canvas');layer.width=map.width;layer.height=map.height;layer.getContext('2d').putImageData(pixels,0,0);const bounds=map.observed_bounds||[0,0,map.width-1,map.height-1],padding=12,sx=Math.max(0,bounds[0]-padding),ex=Math.min(map.width-1,bounds[2]+padding),bottom=Math.max(0,bounds[1]-padding),top=Math.min(map.height-1,bounds[3]+padding),sy=map.height-1-top,sw=ex-sx+1,sh=top-bottom+1,scale=Math.min(canvas.width/sw,canvas.height/sh),drawWidth=sw*scale,drawHeight=sh*scale,offsetX=(canvas.width-drawWidth)/2,offsetY=(canvas.height-drawHeight)/2;ctx.imageSmoothingEnabled=false;ctx.fillStyle='#0b1015';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(layer,sx,sy,sw,sh,offsetX,offsetY,drawWidth,drawHeight);const pose=map.localization?.pose;if(pose){const cellX=(pose.x_m-map.origin_x_m)/map.resolution_m,cellY=(pose.y_m-map.origin_y_m)/map.resolution_m,x=offsetX+(cellX-sx)*scale,y=offsetY+(top-cellY)*scale,angle=-pose.yaw_rad;ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.fillStyle='#72d6c9';ctx.strokeStyle='#07110f';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(18,0);ctx.lineTo(-11,-10);ctx.lineTo(-6,0);ctx.lineTo(-11,10);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore()}document.querySelector('#map-meta').textContent=`revision ${map.revision} · observed ${map.observed_cells} cells · ${map.localization?.pose_source||'unlocalized'}${pose?` · x ${pose.x_m.toFixed(2)} m · y ${pose.y_m.toFixed(2)} m`:''}`}catch(error){document.querySelector('#map-meta').textContent='Map unavailable: '+error}}
async function refresh(){try{const [state,tof,persona]=await Promise.all([checked('/api/state'),checked('/api/tof'),checked('/api/autonomy')]);const imu=state.imu||{};
const scene=persona.scene||{},depth=persona.depth||{};document.querySelector('#updated').innerHTML='<span class="ok">Connected</span> · sim_time '+Number(state.sim_time||0).toFixed(2)+' s · trunk '+(state.trunk||[]).map(x=>Number(x).toFixed(3)).join(', ');
document.querySelector('#scene').innerHTML=[metric('Free floor',scene.free_floor||'unknown'),metric('Visibility',scene.visibility||'unknown'),metric('Entities',(scene.entities||[]).map(x=>x.kind).join(', ')||'none'),metric('Hazards',(scene.hazards||[]).join(', ')||'none'),metric('ToF clearance',[depth.left_clearance_mm,depth.center_clearance_mm,depth.right_clearance_mm].map(x=>x==null?'?':Math.round(x)).join(' / '),'mm'),metric('Drop memory',depth.drop_hazard_remembered?'latched':'clear')].join('');
document.querySelector('#scene-summary').textContent=scene.summary||persona.observation||'No completed scene interpretation.';
document.querySelector('#persona').innerHTML=[metric('State',persona.state||'unknown'),metric('Action',(persona.actions||[]).join(' + ')||'none'),metric('Voice',persona.voice_style||'none'),metric('Age',Number(persona.age_seconds||0).toFixed(0),'s')].join('');
document.querySelector('#persona-utterance').textContent=persona.utterance||persona.message||'No persona utterance.';
const actionsEnabled=persona.actions_enabled!==false,actionsToggle=document.querySelector('#actions-toggle');actionsToggle.textContent=actionsEnabled?'Disable all actions':'Enable all actions';actionsToggle.classList.toggle('active',!actionsEnabled);document.querySelectorAll('button:not(#actions-toggle):not(#stop),select').forEach(control=>control.disabled=!actionsEnabled);
document.querySelector('#metrics').innerHTML=[metric('Trunk Z',Number(state.trunk_z||0).toFixed(3),'m'),metric('Voltage',Number(state.volts||7.4).toFixed(2),'V'),metric('X velocity',Number((state.base_velocity||[0])[0]||0).toFixed(3),'m/s'),metric('Temperature',Number((state.temps_c||[32])[0]||32).toFixed(1),'°C')].join('');
document.querySelector('#imu').innerHTML=[metric('Gravity', (imu.gravity||[]).map(x=>Number(x).toFixed(2)).join(', ')),metric('Gyroscope',(imu.gyro||[]).map(x=>Number(x).toFixed(2)).join(', ')),metric('Quaternion',(imu.quat||[]).map(x=>Number(x).toFixed(2)).join(', '))].join('');
document.querySelector('#joints').innerHTML=(state.positions||[]).map((v,i)=>`<div class="joint"><span>J${i}</span><code>${Number(v).toFixed(3)} rad</code></div>`).join('');
const values=tof.distance_mm||[], max=Math.max(1,...values);document.querySelector('#tof').innerHTML=values.map((v,i)=>{const ratio=v?Math.min(1,v/max):0;const color=v?`hsl(${Math.round(190-190*ratio)},80%,60%)`:'#394550';return `<div class="zone" title="zone ${i}: ${v||'no target'} mm" style="background:${color}">${v?Math.round(v):'·'}</div>`}).join('');
}catch(error){document.querySelector('#updated').innerHTML='<span class="warning">Disconnected: '+esc(error)+'</span>'}}
const status=text=>document.querySelector('#control-status').textContent=text;
const actionsToggle=document.createElement('button');actionsToggle.id='actions-toggle';actionsToggle.className='danger';actionsToggle.textContent='Disable all actions';document.querySelector('#manual').parentElement.prepend(actionsToggle);
document.querySelector('#manual').onclick=()=>post('/api/persona/pause').then(()=>status('Manual control owns the robot.')).catch(status);
document.querySelector('#resume').onclick=()=>post('/api/persona/resume').then(()=>status('Persona owns the robot.')).catch(status);
actionsToggle.onclick=()=>{const enable=actionsToggle.textContent.startsWith('Enable');post(enable?'/api/actions/enable':'/api/actions/disable').then(()=>status(enable?'All robot actions enabled.':'All robot actions disabled and robot stopped.')).then(refresh).catch(status)};
document.querySelector('#stop').onclick=()=>post('/api/control',{action:'stop'}).then(()=>status('Stop accepted.')).catch(status);
document.querySelectorAll('[data-action]').forEach(button=>button.onclick=()=>post('/api/control',{action:button.dataset.action}).catch(status));
document.querySelectorAll('[data-skill]').forEach(button=>button.onclick=()=>post('/api/control',{action:'skill',skill:button.dataset.skill}).catch(status));
document.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>post('/api/control',{action:'mode',mode:button.dataset.mode}).catch(status));
document.querySelectorAll('[data-theremin]').forEach(button=>button.onclick=()=>post('/api/control',{action:'theremin',active:button.dataset.theremin==='true'}).catch(status));
document.querySelectorAll('[data-chorale]').forEach(button=>button.onclick=()=>post('/api/control',{action:'chorale',active:button.dataset.chorale==='true'}).catch(status));
document.querySelectorAll('[data-look]').forEach(button=>button.onclick=()=>post('/api/control',{action:'look',...JSON.parse(button.dataset.look)}).catch(status));
document.querySelector('#sound-play').onclick=()=>post('/api/control',{action:'sound',tag:document.querySelector('#sound').value}).catch(status);
document.querySelectorAll('[data-move]').forEach(button=>{let timer;const end=()=>{clearInterval(timer);timer=null;post('/api/control',{action:'stop'}).catch(status);button.classList.remove('active')};button.onpointerdown=()=>{const twist=JSON.parse(button.dataset.move);post('/api/persona/pause').then(()=>post('/api/control',{action:'move',...twist})).catch(status);timer=setInterval(()=>post('/api/control',{action:'move',...twist}).catch(status),100);button.classList.add('active')};button.onpointerup=end;button.onpointercancel=end;button.onpointerleave=()=>{if(timer)end()}});
let browserPad=false,previousButtons=[],padMode='drive',padModeRoller=false,backHeld=0,upHeld=0,lastRt=0,lastLt=0;
document.querySelector('#gamepad').onclick=()=>{browserPad=!browserPad;document.querySelector('#gamepad').classList.toggle('active',browserPad);if(browserPad)post('/api/persona/pause').then(()=>status('Browser gamepad active.')).catch(status);else post('/api/control',{action:'stop'}).then(()=>post('/api/persona/resume')).then(()=>status('Persona owns the robot.')).catch(status)};
setInterval(()=>{if(!browserPad)return;const pad=navigator.getGamepads?.()[0];if(!pad){status('Waiting for browser gamepad...');return}const dead=v=>Math.abs(v)<0.1?0:v;const buttons=pad.buttons.map(x=>x.pressed);const edge=i=>buttons[i]&&!previousButtons[i];const lx=dead(pad.axes[0]||0),ly=dead(pad.axes[1]||0),rx=dead(pad.axes[2]||0),ry=dead(pad.axes[3]||0),rt=pad.buttons[7]?.value||0,lt=pad.buttons[6]?.value||0;
if(edge(9))post('/api/control',{action:'enable_toggle'}).catch(status);if(edge(3)){padMode=padMode==='head'?'drive':'head';status(`Browser gamepad: ${padMode} mode.`)}if(edge(1)){padMode=padMode==='body'?'drive':'body';status(`Browser gamepad: ${padMode} mode.`)}
if(edge(0))post('/api/control',{action:'skill',skill:'ground_pick'}).catch(status);if(edge(2))post('/api/control',{action:'skill',skill:'roulade'}).catch(status);else if(buttons[2])post('/api/control',{action:'skill',skill:'roulade',notify:true}).catch(status);if(edge(4))post('/api/control',{action:'skill',skill:'kick_left'}).catch(status);if(edge(5))post('/api/control',{action:'skill',skill:'kick_right'}).catch(status);if(edge(13))post('/api/control',{action:'skill',skill:'sit_toggle'}).catch(status);
if(buttons[8]){if(!backHeld)backHeld=performance.now();else if(performance.now()-backHeld>2000){post('/api/control',{action:'shutdown'}).catch(status);backHeld=Infinity}}else backHeld=0;if(buttons[12]){if(!upHeld)upHeld=performance.now();else if(performance.now()-upHeld>3000){padModeRoller=!padModeRoller;post('/api/control',{action:'mode',mode:padModeRoller?'roller':'walk'}).catch(status);upHeld=Infinity}}else upHeld=0;
if(padMode==='drive')post('/api/control',{action:'move',vx:-ly*0.3,vy:-lx*0.3,vyaw:-rx*1.5}).catch(status);else if(padMode==='head')post('/api/control',{action:'head',neck_pitch:-ry*2.5,head_pitch:ly*2.5,head_yaw:-lx*2.5,head_roll:rx*2.5}).catch(status);else{const leftY=-ly,rightY=-ry;post('/api/control',{action:'pose',z:leftY*(leftY>=0?0.01:0.025),roll:rx*0.2618,pitch:rightY*0.2618,active:true}).catch(status)}
post('/api/control',{action:'mouth',opening:Math.max(rt,lt)}).catch(status);if(lastRt<0.3&&rt>=0.3)post('/api/control',{action:'sound',tag:'chirp'}).catch(status);if(lt>=0.3)post('/api/control',{action:'sound',tag:'wheee',hold:true}).catch(status);else if(lastLt>=0.3)post('/api/control',{action:'sound',tag:'wheee',hold:false}).catch(status);lastRt=rt;lastLt=lt;previousButtons=buttons},50);
refresh();setInterval(refresh,33);refreshMap();setInterval(refreshMap,1000);
</script></body></html>"""


_DASHBOARD_TABS_CSS = """
<style>
body{background:linear-gradient(145deg,#0d1215 0%,#151b1d 48%,#171614 100%)}
main{max-width:1320px}.app-header{display:flex;align-items:end;justify-content:space-between;gap:18px;margin-bottom:14px;border-bottom:1px solid #34413f;padding-bottom:14px}
.app-header p{margin:0}.tabs{display:flex;gap:4px;margin:0 0 16px;border-bottom:1px solid #34413f}.tab{appearance:none;border:0;border-bottom:3px solid transparent;background:transparent;color:#9eaaa8;padding:11px 16px;font:700 13px Georgia,serif;letter-spacing:0;cursor:pointer}.tab:hover{color:#f0f3ee}.tab[aria-selected="true"]{color:#79d6c7;border-bottom-color:#d97757}.tab-panel{display:none}.tab-panel.active{display:grid}.map-health{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0 0 12px}.map-health .metric{border-left:3px solid #53615e}.map-health .live{color:#79d6c7}.map-health .delayed{color:#f4bf68}.map-health .stale{color:#ed806e}.card{box-shadow:0 8px 28px rgba(0,0,0,.16)}
@media(max-width:700px){main{padding:12px}.app-header{display:block}.tabs{position:sticky;top:0;z-index:5;background:#101619}.tab{flex:1;padding:11px 6px}.map-health{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:1fr}.card{padding:11px}}
</style>
"""

_DASHBOARD_TABS_SCRIPT = """
const main=document.querySelector('main'),title=main.querySelector('h1'),connection=document.querySelector('#updated');
const header=document.createElement('header');header.className='app-header';title.before(header);header.append(title,connection);
const tabs=document.createElement('nav');tabs.className='tabs';tabs.setAttribute('aria-label','Command center views');
const groups={control:['Camera input','Scene semantics','Autonomous persona','Command center'],mapping:['Persistent occupancy map','ToF / lidar 8×8'],systems:['Available actions and controller mapping','Robot state','IMU','Joints']};
const labels={control:'Control',mapping:'Mapping',systems:'Systems'},panels={};
for(const [name,headings] of Object.entries(groups)){const button=document.createElement('button');button.className='tab';button.type='button';button.dataset.tab=name;button.textContent=labels[name];button.setAttribute('aria-controls',`panel-${name}`);tabs.append(button);const panel=document.createElement('section');panel.className='grid tab-panel';panel.id=`panel-${name}`;panel.dataset.panel=name;for(const article of [...document.querySelectorAll('article')]){if(headings.includes(article.querySelector('h2')?.textContent))panel.append(article)}panels[name]=panel;main.append(panel)}
main.querySelector('section.grid:empty')?.remove();header.after(tabs);
const selectTab=name=>{const selected=panels[name]?name:'control';for(const button of tabs.querySelectorAll('.tab'))button.setAttribute('aria-selected',String(button.dataset.tab===selected));for(const [key,panel] of Object.entries(panels))panel.classList.toggle('active',key===selected);history.replaceState(null,'',`#${selected}`)};
tabs.addEventListener('click',event=>{const button=event.target.closest('.tab');if(button)selectTab(button.dataset.tab)});selectTab(location.hash.slice(1)||'control');
const mapArticle=[...document.querySelectorAll('article')].find(article=>article.querySelector('h2')?.textContent==='Persistent occupancy map');
const mapHealth=document.createElement('div');mapHealth.id='map-health';mapHealth.className='map-health';mapArticle.querySelector('h2').after(mapHealth);
const baseRefreshMap=refreshMap;refreshMap=async()=>{await baseRefreshMap();try{const map=await checked('/api/map'),state=map.status||'stale';mapHealth.innerHTML=[metric('Acquisition',state),metric('Last scan',Number(map.age_seconds||0).toFixed(1),'s ago'),metric('Occupied',map.occupied_cells,'cells'),metric('Free',map.free_cells,'cells')].join('');mapHealth.querySelector('.metric b').classList.add(state);document.querySelector('#map-meta').textContent+=` · ${state}`}catch(error){mapHealth.innerHTML=metric('Acquisition','unavailable')}};
"""

DASHBOARD = DASHBOARD.replace("</head>", _DASHBOARD_TABS_CSS + "</head>").replace(
    "refresh();setInterval(refresh,33);refreshMap();setInterval(refreshMap,1000);",
    _DASHBOARD_TABS_SCRIPT
    + "refresh();setInterval(refresh,33);refreshMap();setInterval(refreshMap,1000);",
)


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_STATUS_BYTES = 64 * 1024
MAX_MAP_BYTES = 4 * 1024 * 1024
TELEMETRY_HZ = 30.0
TELEMETRY_PERIOD = 1.0 / TELEMETRY_HZ
CONTROL_ACTIONS = (
    "stop",
    "move",
    "enable_toggle",
    "init",
    "relax",
    "shutdown",
    "skill",
    "sound",
    "head",
    "look",
    "pose",
    "mouth",
    "mode",
    "theremin",
    "chorale",
)
CONTROL_SKILLS = frozenset({"sit_toggle", "ground_pick", "kick_left", "kick_right", "roulade"})
CONTROL_SOUNDS = frozenset({"alarm", "greet", "inquire", "peck", "chirp", "coo", "wheee"})


def dispatch_control(host: str, port: int, command: object) -> None:  # pylint: disable=too-many-branches
    if not isinstance(command, dict) or not isinstance(command.get("action"), str):
        raise ValueError("control command requires an action")
    action = command["action"]
    if action not in CONTROL_ACTIONS:
        raise ValueError(f"unsupported control action: {action}")
    robot = RobotdClient(host=host, port=port)
    robot.connect()
    try:
        if action == "stop":
            robot.stop()
        elif action == "move":
            vx = _bounded_number(command, "vx", 0.3)
            vy = _bounded_number(command, "vy", 0.3)
            vyaw = _bounded_number(command, "vyaw", 1.5)
            robot.move_twist(vx, vy, vyaw)
        elif action == "enable_toggle":
            robot.toggle_enable()
        elif action == "init":
            robot.init()
        elif action == "relax":
            robot.relax()
        elif action == "shutdown":
            robot.shutdown()
        elif action == "skill":
            skill = command.get("skill")
            if skill not in CONTROL_SKILLS:
                raise ValueError("unsupported skill")
            notify = command.get("notify", False)
            if not isinstance(notify, bool):
                raise ValueError("skill notify must be boolean")
            robot.skill(str(skill), notify=notify)
        elif action == "sound":
            tag = command.get("tag")
            if tag not in CONTROL_SOUNDS:
                raise ValueError("unsupported sound")
            hold = command.get("hold")
            if hold is not None and not isinstance(hold, bool):
                raise ValueError("sound hold must be boolean")
            robot.sound(str(tag), hold)
        elif action == "head":
            robot.head(
                _bounded_number(command, "neck_pitch", 2.5),
                _bounded_number(command, "head_pitch", 2.5),
                _bounded_number(command, "head_yaw", 2.5),
                _bounded_number(command, "head_roll", 2.5),
            )
        elif action == "look":
            robot.look(
                _bounded_number(command, "x", 2.0, minimum=0.05),
                _bounded_number(command, "y", 2.0),
                _bounded_number(command, "z", 2.0),
                _bounded_number(command, "neck_pitch", 1.0),
            )
        elif action == "pose":
            active = command.get("active", True)
            if not isinstance(active, bool):
                raise ValueError("pose active must be boolean")
            robot.pose(
                _bounded_number(command, "z", 0.025),
                _bounded_number(command, "roll", 0.2618),
                _bounded_number(command, "pitch", 0.2618),
                active=active,
            )
        elif action == "mouth":
            robot.mouth(_bounded_number(command, "opening", 1.0, minimum=0.0))
        elif action == "mode":
            mode = command.get("mode")
            if mode not in {"walk", "roller"}:
                raise ValueError("mode must be walk or roller")
            robot.set_mode(str(mode))
        elif action == "theremin":
            active = command.get("active")
            if not isinstance(active, bool):
                raise ValueError("theremin active must be boolean")
            robot.theremin(active)
        else:
            active = command.get("active")
            piece = command.get("piece")
            if not isinstance(active, bool):
                raise ValueError("chorale active must be boolean")
            if piece is not None and (isinstance(piece, bool) or not isinstance(piece, int)):
                raise ValueError("chorale piece must be an integer")
            robot.chorale(active, piece)
    finally:
        robot.close()


def _bounded_number(
    command: dict[object, object], name: str, maximum: float, *, minimum: float | None = None
) -> float:
    value = command.get(name, 0.0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    lower = -maximum if minimum is None else minimum
    if not math.isfinite(result) or not lower <= result <= maximum:
        raise ValueError(f"{name} is outside its allowed range")
    return result


def read_autonomy_status(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {"state": "stopped", "message": "Persona not started", "age_seconds": 0.0}
    if path.stat().st_size > MAX_STATUS_BYTES:
        raise RuntimeError("autonomy status exceeds the size limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("autonomy status is unreadable") from error
    if not isinstance(value, dict):
        raise RuntimeError("autonomy status must be an object")
    updated_at = value.get("updated_at")
    if not isinstance(updated_at, int | float):
        raise RuntimeError("autonomy status has no timestamp")
    result: dict[str, object] = dict(value)
    result["age_seconds"] = max(0.0, time.time() - float(updated_at))
    if result["age_seconds"] > 300:
        result["state"] = "stale"
        result["message"] = "No recent persona update"
    observation = result.get("observation")
    if isinstance(observation, str):
        result["observation"] = observation[:500]
    return result


def actions_are_enabled(path: Path | None) -> bool:
    return path is None or not path.exists()


def read_mapping(map_path: Path | None, localization_path: Path | None) -> dict[str, object]:
    if map_path is None or not map_path.is_file():
        raise RuntimeError("occupancy map is not available")
    map_stat = map_path.stat()
    if map_stat.st_size > MAX_MAP_BYTES:
        raise RuntimeError("occupancy map exceeds the size limit")
    try:
        document = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("occupancy map is unreadable") from error
    width = document.get("width")
    height = document.get("height")
    evidence = document.get("evidence")
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or not isinstance(evidence, list)
        or len(evidence) != width * height
    ):
        raise RuntimeError("occupancy map dimensions are invalid")
    if any(type(value) is not int or not -10 <= value <= 10 for value in evidence):
        raise RuntimeError("occupancy map evidence is invalid")
    cells = [0 if value <= -2 else 100 if value >= 2 else -1 for value in evidence]
    free_cells = cells.count(0)
    occupied_cells = cells.count(100)
    unknown_cells = cells.count(-1)
    observed_indices = [index for index, value in enumerate(cells) if value != -1]
    observed = len(observed_indices)
    localization: object = None
    if localization_path is not None and localization_path.is_file():
        if localization_path.stat().st_size > MAX_STATUS_BYTES:
            raise RuntimeError("localization state exceeds the size limit")
        try:
            localization = json.loads(localization_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("localization state is unreadable") from error
        if not isinstance(localization, dict):
            raise RuntimeError("localization state must be an object")
    pose = localization.get("pose") if isinstance(localization, dict) else None
    bounds_indices = list(observed_indices)
    if isinstance(pose, dict):
        try:
            pose_column = math.floor(
                (float(pose["x_m"]) - float(document["origin_x_m"]))
                / float(document["resolution_m"])
            )
            pose_row = math.floor(
                (float(pose["y_m"]) - float(document["origin_y_m"]))
                / float(document["resolution_m"])
            )
            if 0 <= pose_column < width and 0 <= pose_row < height:
                bounds_indices.append(pose_row * width + pose_column)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
    columns = [index % width for index in bounds_indices]
    rows = [index // width for index in bounds_indices]
    observed_bounds = (
        [min(columns), min(rows), max(columns), max(rows)]
        if bounds_indices
        else [0, 0, width - 1, height - 1]
    )
    age_seconds = max(0.0, time.time() - map_stat.st_mtime)
    status = "live" if age_seconds <= 2.0 else "delayed" if age_seconds <= 10.0 else "stale"
    return {
        "schema_version": document.get("schema_version"),
        "resolution_m": document.get("resolution_m"),
        "width": width,
        "height": height,
        "origin_x_m": document.get("origin_x_m"),
        "origin_y_m": document.get("origin_y_m"),
        "revision": document.get("revision", 0),
        "cells": cells,
        "coverage_percent": observed * 100.0 / len(cells),
        "observed_cells": observed,
        "free_cells": free_cells,
        "occupied_cells": occupied_cells,
        "unknown_cells": unknown_cells,
        "observed_bounds": observed_bounds,
        "updated_at": map_stat.st_mtime,
        "age_seconds": age_seconds,
        "status": status,
        "localization": localization,
    }


def read_simulator(host: str, port: int, operation: str) -> dict[str, object]:
    with socket.create_connection((host, port)) as connection:
        stream = connection.makefile("rw", encoding="utf-8", newline="\n")
        stream.write(
            json.dumps(
                {"op": "hello", "protocol": 1, "joints": 15}, allow_nan=False
            )
            + "\n"
        )
        stream.flush()
        if _read_response(stream).get("protocol") != 1:
            raise RuntimeError("simulator protocol mismatch")
        stream.write(json.dumps({"op": operation}, allow_nan=False) + "\n")
        stream.flush()
        answer = _read_response(stream)
        if "error" in answer:
            raise RuntimeError(str(answer["error"]))
        return answer


def _read_response(stream: object) -> dict[str, object]:
    line = stream.readline(MAX_RESPONSE_BYTES + 1)  # type: ignore[attr-defined]
    if not line or len(line.encode("utf-8")) > MAX_RESPONSE_BYTES or not line.endswith("\n"):
        raise RuntimeError("simulator response exceeds the framing limit")
    try:
        answer = json.loads(line, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("simulator returned invalid JSON") from error
    if not isinstance(answer, dict):
        raise RuntimeError("simulator response must be an object")
    return answer


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def read_state(host: str, port: int) -> dict[str, object]:
    state = read_simulator(host, port, "read")
    state.update(read_simulator(host, port, "slow"))
    return state


def read_camera(host: str, port: int) -> bytes:
    frame = read_simulator(host, port, "camera")
    encoded = frame.get("jpeg_base64")
    if not isinstance(encoded, str):
        raise RuntimeError("simulator camera response has no JPEG frame")
    return base64.b64decode(encoded, validate=True)


class SimulatorCache:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._values: dict[str, tuple[float, object]] = {}
        self.last_success: float | None = None
        self.last_error: str | None = None

    def get(self, key: str, maximum_age: float) -> object:
        now = time.monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None and now - cached[0] <= maximum_age:
                return cached[1]
            try:
                if key == "state":
                    value: object = read_state(self._host, self._port)
                elif key == "camera":
                    value = read_camera(self._host, self._port)
                else:
                    value = read_simulator(self._host, self._port, key)
            except (OSError, RuntimeError, ValueError) as error:
                self.last_error = str(error)
                raise
            self._values[key] = (now, value)
            self.last_success = now
            self.last_error = None
            return value


class Handler(BaseHTTPRequestHandler):
    simulator_host = "127.0.0.1"
    simulator_port = 7801
    cache = SimulatorCache(simulator_host, simulator_port)
    autonomy_status_file: Path | None = None
    manual_active_file: Path | None = None
    actions_disabled_file: Path | None = None
    map_file: Path | None = None
    localization_file: Path | None = None
    control_enabled = False
    robot_host = "127.0.0.1"
    robot_port = 8765

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", DASHBOARD.encode())
            elif self.path == "/api/state":
                self._send_json(self.cache.get("state", TELEMETRY_PERIOD))
            elif self.path == "/api/tof":
                self._send_json(self.cache.get("tof", TELEMETRY_PERIOD))
            elif self.path == "/api/camera.jpg":
                jpeg = self.cache.get("camera", TELEMETRY_PERIOD)
                if not isinstance(jpeg, bytes):
                    raise RuntimeError("camera cache returned an invalid frame")
                self._send(200, "image/jpeg", jpeg)
            elif self.path == "/api/camera/stream":
                self._stream_camera()
            elif self.path == "/api/health":
                self.cache.get("state", 0.5)
                self._send_json({"status": "ok", "simulator": "connected"})
            elif self.path == "/api/autonomy":
                status = read_autonomy_status(self.autonomy_status_file)
                status["actions_enabled"] = actions_are_enabled(self.actions_disabled_file)
                self._send_json(status)
            elif self.path == "/api/map":
                self._send_json(read_mapping(self.map_file, self.localization_file))
            else:
                self._send_json({"error": "not found"}, 404)
        except (OSError, RuntimeError, ValueError) as error:
            self._send_json({"error": str(error)}, 503)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/actions/disable" and self.control_enabled:
                if self.actions_disabled_file is None:
                    raise RuntimeError("action safety file is not configured")
                self.actions_disabled_file.parent.mkdir(parents=True, exist_ok=True)
                self.actions_disabled_file.touch()
                dispatch_control(self.robot_host, self.robot_port, {"action": "stop"})
                self._send_json({"status": "ok", "actions_enabled": False})
                return
            if self.path == "/api/actions/enable" and self.control_enabled:
                if self.actions_disabled_file is not None:
                    self.actions_disabled_file.unlink(missing_ok=True)
                self._send_json({"status": "ok", "actions_enabled": True})
                return
            if self.path == "/api/persona/pause" and self.control_enabled:
                if self.manual_active_file is None:
                    raise RuntimeError("manual control file is not configured")
                self.manual_active_file.parent.mkdir(parents=True, exist_ok=True)
                self.manual_active_file.touch()
                self._send_json({"status": "ok", "persona": "paused"})
                return
            if self.path == "/api/persona/resume" and self.control_enabled:
                if self.manual_active_file is not None:
                    self.manual_active_file.unlink(missing_ok=True)
                self._send_json({"status": "ok", "persona": "active"})
                return
            if self.path != "/api/control" or not self.control_enabled:
                self._send_json({"error": "control is disabled"}, 403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_STATUS_BYTES:
                raise ValueError("control request has an invalid size")
            command = json.loads(self.rfile.read(length))
            if (
                not actions_are_enabled(self.actions_disabled_file)
                and isinstance(command, dict)
                and command.get("action") != "stop"
            ):
                self._send_json({"error": "all robot actions are disabled"}, 423)
                return
            dispatch_control(self.robot_host, self.robot_port, command)
            self._send_json({"status": "accepted"})
        except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as error:
            self._send_json({"error": str(error)}, 400)

    def _send_json(self, value: object, status: int = 200) -> None:
        self._send(status, "application/json", json.dumps(value, allow_nan=False).encode())

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_camera(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        next_frame = time.monotonic()
        try:
            while True:
                jpeg = self.cache.get("camera", TELEMETRY_PERIOD)
                if not isinstance(jpeg, bytes):
                    raise RuntimeError("camera cache returned an invalid frame")
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                next_frame += TELEMETRY_PERIOD
                remaining = next_frame - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
                elif remaining < -TELEMETRY_PERIOD:
                    next_frame = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError, RuntimeError, ValueError):
            pass

    def log_message(self, format: str, *args: object) -> None:  # pylint: disable=redefined-builtin
        if self.client_address[0] not in {"127.0.0.1", "::1"}:
            print(f"telemetry client {self.client_address[0]}: {format % args}", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Web telemetry dashboard for a MicroDuck simulator"
    )
    parser.add_argument("--simulator-host", default="127.0.0.1")
    parser.add_argument("--simulator-port", type=int, default=7801)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8780)
    parser.add_argument("--autonomy-status-file", type=Path)
    parser.add_argument("--manual-active-file", type=Path)
    parser.add_argument("--actions-disabled-file", type=Path)
    parser.add_argument("--map-file", type=Path)
    parser.add_argument("--localization-file", type=Path)
    parser.add_argument("--enable-control", action="store_true")
    parser.add_argument("--robot-host", default="127.0.0.1")
    parser.add_argument("--robot-port", type=int, default=8765)
    args = parser.parse_args(argv)
    Handler.simulator_host = args.simulator_host
    Handler.simulator_port = args.simulator_port
    Handler.cache = SimulatorCache(args.simulator_host, args.simulator_port)
    Handler.autonomy_status_file = args.autonomy_status_file
    Handler.manual_active_file = args.manual_active_file
    Handler.actions_disabled_file = args.actions_disabled_file
    Handler.map_file = args.map_file
    Handler.localization_file = args.localization_file
    Handler.control_enabled = args.enable_control
    Handler.robot_host = args.robot_host
    Handler.robot_port = args.robot_port
    with ThreadingHTTPServer((args.listen_host, args.listen_port), Handler) as server:
        print(f"telemetry dashboard listening on {args.listen_host}:{args.listen_port}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
