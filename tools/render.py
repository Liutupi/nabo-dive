#!/usr/bin/env python3
"""Fixed-phase swim/dash_in/dash/dash_out renderer for three skins."""
from pathlib import Path
from fractions import Fraction
import sys, argparse, json, math, io, copy, hashlib, base64, re
import xml.etree.ElementTree as ET
import numpy as np
import cairosvg
from PIL import Image, ImageDraw, ImageFont
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[1]
ZONES=['#3FA9D6','#1B5E8C','#0B2A4A','#061528','#04070D']
ZONE_NAMES=['SUNLIT','TWILIGHT','MIDNIGHT','ABYSS','HADAL']
GIF_MS=[80,90,80,80,90,80,80,90]
FONT='/System/Library/Fonts/Supplemental/Arial.ttf'
FONT_BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
SVG_NS='http://www.w3.org/2000/svg'
ET.register_namespace('',SVG_NS)
_CACHE={}
ANIMATIONS=['swim','dash_in','dash','dash_out','gulp','hit','lowair','out','turn']

def load_rig():return json.loads((BASE/'rig/rig.json').read_text())
def load_animation(name='swim'):
 if name not in ANIMATIONS:raise ValueError('Only swim and the three dash clips are authorized.')
 return json.loads((BASE/f'rig/animations/{name}.json').read_text())

def periodic(values,phase):
 """Periodic cubic Hermite/Catmull-Rom. Endpoint values AND tangents match."""
 n=len(values);u=(phase%1.0)*n;i=math.floor(u);t=u-i
 p0,p1,p2,p3=[values[j%n] for j in [i-1,i,i+1,i+2]]
 limited=lambda a,b: 0.0 if a*b<=0 else 2*a*b/(a+b)
 m1=limited(p1-p0,p2-p1);m2=limited(p2-p1,p3-p2)
 return (2*t**3-3*t*t+1)*p1+(t**3-2*t*t+t)*m1+(-2*t**3+3*t*t)*p2+(t**3-t*t)*m2

class Pose(dict):
 """Rotation channels with local joint offsets; root and chest remain fixed."""
 pass

def clamped(values,phases,phase):
 p=max(0.,min(1.,phase))
 if p<=phases[0]:return values[0]
 if p>=phases[-1]:return values[-1]
 i=next(i for i in range(len(phases)-1) if phases[i]<=p<phases[i+1]);h=phases[i+1]-phases[i];t=(p-phases[i])/h
 slopes=[(values[j+1]-values[j])/(phases[j+1]-phases[j]) for j in range(len(values)-1)]
 limited=lambda a,b:0.0 if a*b<=0 else 2*a*b/(a+b)
 m0=0. if i==0 else limited(slopes[i-1],slopes[i]);m1=0. if i+1==len(values)-1 else limited(slopes[i],slopes[i+1])
 return (2*t**3-3*t*t+1)*values[i]+(t**3-2*t*t+t)*h*m0+(-2*t**3+3*t*t)*values[i+1]+(t**3-t*t)*h*m1

def pose_at(phase,rig=None,anim=None):
 rig=rig or load_rig();anim=anim or load_animation()
 sample=(lambda values:periodic(values,phase)) if anim['loop'] else (lambda values:clamped(values,[f['phase'] for f in anim['keyframes']],phase))
 pose=Pose({name:sample([f['rotations'].get(name,0.) for f in anim['keyframes']]) for name in rig['bones']})
 pose.offsets={name:[sample([f.get('translations',{}).get(name,[0,0])[axis] for f in anim['keyframes']]) for axis in range(2)] for name in rig['bones']}
 secondary=anim.get('secondary',{})
 if 'driver' in secondary:
  lag=secondary['lag_frames']/anim['frame_count']
  for name,spec in secondary['nodes'].items():pose[name]=spec['gain']*periodic(secondary['driver'],phase-lag+spec['phase_offset'])
 pose.expressions=min(anim['keyframes'],key=lambda f:abs(f['phase']-(phase%1 if anim['loop'] else max(0,min(1,phase))))).get('expressions',{})
 pose.front_mix=sample([f.get('front_mix',0.) for f in anim['keyframes']]);pose.relaxed_mix=sample([f.get('relaxed_mix',0.) for f in anim['keyframes']]);pose.facing_angle=sample([f.get('facing_angle',50.) for f in anim['keyframes']])
 pose.front_rotations={name:sample([f.get('front_rotations',{}).get(name,0.) for f in anim['keyframes']]) for name in rig['bones']}
 pose.cloth_mix=sample([f.get('cloth_mix',0.) for f in anim['keyframes']]) if not anim['loop'] else (1. if anim['name']=='dash' else 0.)
 return pose

def translate(x,y):return np.array([[1.,0,x],[0,1.,y],[0,0,1.]])
def rotate(deg):
 a=math.radians(deg);return np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1.]])
def matrices(pose,rig,angle=50,scale=1,mirror=False):
 ax,ay=rig['anchor'];angle=angle+getattr(pose,'facing_angle',50.)-50.
 if getattr(pose,'front_mix',0)>0:
  rig,pose=front_pose_and_rig(pose,rig)
 flip=np.diag([-1. if mirror else 1.,1.,1.]);s=np.diag([scale,scale,1.])
 world=translate(ax,ay)@flip@rotate(-90-angle)@s@translate(-ax,-ay)
 result={}
 def node(name):
  if name in result:return result[name]
  b=rig['bones'][name];parent=world if b['parent'] is None else node(b['parent'])
  x,y=b['pivot'];dx,dy=getattr(pose,'offsets',{}).get(name,[0,0]);m=parent@translate(dx,dy)@translate(x,y)@rotate(pose[name])@translate(-x,-y);result[name]=m;return m
 for name in rig['bones']:node(name)
 return result

def point(m,p):return (m@np.array([*p,1.]))[:2].tolist()
def matrix_text(m):return 'matrix('+ ' '.join(f'{x:.9f}' for x in [m[0,0],m[1,0],m[0,1],m[1,1],m[0,2],m[1,2]])+')'
def component(rel):
 if rel not in _CACHE:
  root=ET.parse(BASE/'rig'/rel).getroot();_CACHE[rel]=list(root)
 return [copy.deepcopy(e) for e in _CACHE[rel]]

def contour(d,n=96):
 # Cloth source paths use only absolute M/L/Q/Z. Flatten curves, then match perimeter samples.
 tokens=re.findall(r'[MLQZ]|[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?',d);i=0;points=[];current=None;first=None
 while i<len(tokens):
  cmd=tokens[i];i+=1
  if cmd in ('M','L'):
   current=np.array([float(tokens[i]),float(tokens[i+1])]);i+=2;points.append(current);first=current if first is None else first
  elif cmd=='Q':
   control=np.array([float(tokens[i]),float(tokens[i+1])]);end=np.array([float(tokens[i+2]),float(tokens[i+3])]);i+=4
   for t in np.linspace(0,1,25)[1:]:points.append((1-t)**2*current+2*(1-t)*t*control+t*t*end)
   current=end
  elif cmd=='Z':points.append(first)
  else:raise ValueError('Unsupported cloth command '+cmd)
 arr=np.array(points);dist=np.r_[0,np.cumsum(np.linalg.norm(np.diff(arr,axis=0),axis=1))];targets=np.linspace(0,dist[-1],n,endpoint=False)
 return np.column_stack([np.interp(targets,dist,arr[:,j]) for j in range(2)])

def cloth_component(swim_rel,dash_rel,mix):
 if mix<=0:return component(swim_rel)
 if mix>=1:return component(dash_rel)
 key=('morph',swim_rel,dash_rel)
 if key not in _CACHE:
  roots=[ET.parse(BASE/'rig'/rel).getroot() for rel in [swim_rel,dash_rel]]
  paths=[[e for e in root.iter() if e.tag.split('}')[-1]=='path'] for root in roots]
  pairs=[]
  for j,right in enumerate(paths[1]):
   dst=contour(right.get('d'))
   if j<len(paths[0]):left=paths[0][j];src=contour(left.get('d'))
   else:src=np.tile(np.mean(contour(paths[0][-1].get('d')),axis=0),(len(dst),1))
   pairs.append((src,dst,dict(right.attrib)))
  _CACHE[key]=pairs
 result=[]
 for src,dst,attrs in _CACHE[key]:
  coords=(1-mix)*src+mix*dst;attrs=attrs.copy();attrs['d']='M'+'L'.join(f'{x:.6f} {y:.6f}' for x,y in coords)+'Z';result.append(ET.Element('{'+SVG_NS+'}path',attrs))
 return result

def front_joint_layout(rig,mix):
 views=rig['front_views'];left=views['streamline']['front_pivots'];right=views['relaxed']['front_pivots']
 layout={name:[(1-mix)*left.get(name,b['pivot'])[j]+mix*right.get(name,left.get(name,b['pivot']))[j] for j in range(2)] for name,b in rig['bones'].items()}
 # Interpolate limb direction and projected length, avoiding a collapsed forearm halfway through release.
 shoulder=np.array(left['upper_arm_near']);va=np.array(left['forearm_hand_near'])-shoulder;vb=np.array(right['forearm_hand_near'])-shoulder
 ang_a=math.degrees(math.atan2(va[1],va[0]));ang_b=math.degrees(math.atan2(vb[1],vb[0]));delta=(ang_b-ang_a+180)%360-180
 angle=math.radians(ang_a+mix*delta);length=(1-mix)*np.linalg.norm(va)+mix*np.linalg.norm(vb);elbow=shoulder+length*np.array([math.cos(angle),math.sin(angle)])
 wa=np.array(left['hand_near'])-np.array(left['forearm_hand_near']);wb=np.array(right['hand_near'])-np.array(right['forearm_hand_near'])
 angle=math.radians(clamped([math.degrees(math.atan2(wa[1],wa[0])),-60,0,math.degrees(math.atan2(wb[1],wb[0]))],[0,.32,.65,1],mix));length=(1-mix)*np.linalg.norm(wa)+mix*np.linalg.norm(wb);wrist=elbow+length*np.array([math.cos(angle),math.sin(angle)])
 layout['forearm_hand_near']=elbow.tolist();layout['hand_near']=wrist.tolist();layout['forearm_hand_far']=[256-elbow[0],elbow[1]];layout['hand_far']=[256-wrist[0],wrist[1]]
 return layout

def front_pose_and_rig(pose,rig):
 front=copy.deepcopy(rig);layout=front_joint_layout(rig,pose.relaxed_mix)
 for name,b in front['bones'].items():b['pivot']=layout[name]
 p=Pose(pose.front_rotations);p.offsets={k:[0.,0.] for k in front['bones']}
 return front,p

def front_paths(rel):
 key=('front-paths',rel)
 if key in _CACHE:return _CACHE[key]
 result=[]
 def walk(el,m):
  trans=el.get('transform','')
  for kind,body in re.findall(r'(matrix|translate|scale)\(([^)]*)\)',trans):
   a=[float(v) for v in re.findall(r'[-+]?(?:\d*\.)?\d+',body)]
   if kind=='matrix':t=np.array([[a[0],a[2],a[4]],[a[1],a[3],a[5]],[0,0,1.]])
   elif kind=='translate':t=translate(a[0],a[1] if len(a)>1 else 0)
   else:t=np.diag([a[0],a[1] if len(a)>1 else a[0],1.])
   m=m@t
  if el.tag.split('}')[-1]=='path':
   xy=contour(el.get('d'));xy=(m@np.column_stack([xy,np.ones(len(xy))]).T).T[:,:2];result.append((xy,dict(el.attrib)))
  for c in el:walk(c,m)
 walk(ET.parse(BASE/'rig'/rel).getroot(),np.eye(3));_CACHE[key]=result;return result

def front_component(skin,name,pose,rig):
 a=rig['front_views']['streamline']['skins'][skin]['slots'].get(name);b=rig['front_views']['relaxed']['skins'][skin]['slots'].get(name)
 if not a:return []
 mix=pose.relaxed_mix
 if mix<=0 or a==b:return component(a)
 if mix>=1:return component(b)
 if name not in ['upper_arm_near','upper_arm_far','forearm_hand_near','forearm_hand_far','hand_near','hand_far']:return component(a)
 left=front_paths(a);right=front_paths(b);assert len(left)==len(right);views=rig['front_views'];pa=views['streamline']['front_pivots'];pb=views['relaxed']['front_pivots'];pc=front_joint_layout(rig,mix)
 side='near' if name.endswith('near') else 'far'
 if name.startswith('upper_arm'):start='upper_arm_'+side;end='forearm_hand_'+side
 else:start='forearm_hand_'+side;end='hand_'+side
 oa=np.array(pa[start]);ob=np.array(pb[start]);oc=np.array(pc[start]);va=np.array(pa[end])-oa;vb=np.array(pb[end])-ob;vc=np.array(pc[end])-oc
 la=np.linalg.norm(va);lb=np.linalg.norm(vb);lc=np.linalg.norm(vc);ua=va/la;ub=vb/lb;uc=vc/lc;na=np.array([-ua[1],ua[0]]);nb=np.array([-ub[1],ub[0]]);nc=np.array([-uc[1],uc[0]])
 hand=name.startswith('hand_')
 if hand:oa=np.array(pa[end]);ob=np.array(pb[end]);oc=np.array(pc[end])
 result=[]
 for (src,attrs),(dst,_) in zip(left,right):
  ta=(src-oa)@ua/(1 if hand else la);tb=(dst-ob)@ub/(1 if hand else lb);width=(1-mix)*((src-oa)@na)+mix*((dst-ob)@nb);along=(1-mix)*ta+mix*tb
  xy=oc+np.outer(along*(1 if hand else lc),uc)+np.outer(width,nc);attrs=attrs.copy();attrs.pop('transform',None);attrs['d']='M'+'L'.join(f'{x:.6f} {y:.6f}' for x,y in xy)+'Z';result.append(ET.Element('{'+SVG_NS+'}path',attrs))
 return result

def front_wordmark_mask(skin='a',angle=50,scale=1,mirror=False,rig=None):
 rig=rig or load_rig();anim=load_animation('turn');pose=pose_at(1,rig,anim);ms=matrices(pose,rig,angle,scale,mirror)
 root=ET.Element('{'+SVG_NS+'}svg',{'width':'256','height':'256','viewBox':'0 0 256 256'});g=ET.SubElement(root,'g',{'transform':matrix_text(ms['head'])})
 source=ET.parse(BASE/'rig/common/front/head.svg').getroot()
 for el in source.iter():
  if el.get('id')=='nabo-wordmark':e=copy.deepcopy(el);e.set('fill','#FFFFFF');e.set('stroke','none');g.append(e)
 raw=Image.open(io.BytesIO(cairosvg.svg2png(bytestring=ET.tostring(root),output_width=768,output_height=768))).convert('RGBA').resize((256,256),Image.Resampling.LANCZOS).getchannel('A')
 from PIL import ImageFilter
 return raw.point(lambda v:255 if v else 0).filter(ImageFilter.MaxFilter(5))


def compose_svg(skin,phase,angle=50,scale=1,mirror=False,rig=None,anim=None):
 rig=rig or load_rig();anim=anim or load_animation();pose=pose_at(phase,rig,anim);ms=matrices(pose,rig,angle,scale,mirror)
 root=ET.Element('{'+SVG_NS+'}svg',{'width':'256','height':'256','viewBox':'0 0 256 256'})
 title=ET.SubElement(root,'title');title.text=f'NABO {anim["name"]} v2 / skin {skin} / phase {phase%1:.6f}'
 colors=ET.Element('g',{'id':'colored-parts'})
 for name in rig.get('action_draw_orders',{}).get(anim['name'],rig['draw_order']):
  expr=pose.expressions.get(name)
  if pose.front_mix>0:
   if name=='eyes' and expr=='closed_eye':parts=component('common/front/eyes_closed.svg')
   elif name=='mouth_bubbles':parts=[]
   else:parts=front_component(skin,name,pose,rig)
  elif expr:
   parts=component(rig['expressions'][expr]['path'])
  else:
   rel=rig['skins'][skin].get('animation_overrides',{}).get(anim['name'],{}).get(name,rig['skins'][skin]['slots'].get(name))
   if not rel:continue
   dash_rel=rig['skins'][skin].get('animation_overrides',{}).get('dash',{}).get(name)
   parts=cloth_component(rig['skins'][skin]['slots'][name],dash_rel,pose.cloth_mix) if dash_rel else component(rel)
  if not parts:continue
  g=ET.SubElement(colors,'g',{'id':'bone-'+name,'transform':matrix_text(ms[name])})
  for e in parts:g.append(e)
 # A hard underlay around the entire union; no shadow blur, glow or procedural VFX.
 rim=copy.deepcopy(colors);rim.set('id','outer-rim')
 for e in rim.iter():
  tag=e.tag.split('}')[-1]
  if e.get('id'):e.set('id','rim-'+e.get('id'))
  if tag in ['path','ellipse','rect','circle','polygon']:
   e.set('fill',rig['outline']['rgb'] if e.get('fill')!='none' else 'none');e.set('stroke',rig['outline']['rgb']);e.set('stroke-width',str(rig['outline']['source_stroke_width']));e.set('stroke-linejoin','round');e.set('stroke-linecap','round')
  elif tag=='text':e.set('fill',rig['outline']['rgb']);e.set('stroke',rig['outline']['rgb']);e.set('stroke-width','5')
 root.append(rim);root.append(colors)
 return ET.tostring(root,encoding='unicode')

def make_palette(hexes):
 colors=[tuple(bytes.fromhex(x.lstrip('#'))) for x in hexes]
 out=Image.new('P',(1,1));out.putpalette([v for c in (colors+[colors[-1]]*(256-len(colors))) for v in c]);return out

def quantize_sprite(im,rig,skin):
 im=im.convert('RGBA');pal=make_palette(list(rig['skins'][skin]['palette'].values()))
 rgb=im.convert('RGB').quantize(palette=pal,dither=Image.Dither.NONE).convert('RGB')
 alpha=np.array(im.getchannel('A'),dtype=np.float32);rgb.putalpha(Image.fromarray((np.round(alpha/17)*17).astype('uint8')))
 return rgb

def render_frame(skin,phase,angle=50,scale=1,mirror=False,rig=None,anim=None):
 rig=rig or load_rig();anim=anim or load_animation()
 svg=compose_svg(skin,phase,angle,scale,mirror,rig,anim)
 raw=Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(),output_width=768,output_height=768))).convert('RGBA').resize((256,256),Image.Resampling.LANCZOS)
 out=quantize_sprite(raw,rig,skin)
 if anim['name']=='turn' and phase>=1-1e-9 and abs(angle-50)<1e-9:
  ar=np.array(out);alpha=np.round((ar[:,:,3].astype(float)+ar[:,::-1,3])/34)*17;ar[:,:,3]=alpha.astype('uint8')
  mask=np.array(front_wordmark_mask(skin,angle,scale,mirror,rig))>0;mask=mask|mask[:,::-1]
  for x in range(128):
   take=~(mask[:,x]|mask[:,255-x]);ar[take,255-x,:3]=ar[take,x,:3]
  out=Image.fromarray(ar)
 return out

def frame_info(im,phase,rig,anim,angle,scale,mirror):
 pose=pose_at(phase,rig,anim);ms=matrices(pose,rig,angle,scale,mirror);ar=np.array(im);visible=ar[:,:,3]>0
 actual_rig=front_pose_and_rig(pose,rig)[0] if pose.front_mix>0 else rig
 def landmark(v):
  p=actual_rig['bones'][v['bone']]['pivot'] if pose.front_mix>0 and v['bone'].startswith(('hand_','foot_')) else v['point']
  return point(ms[v['bone']],p)
 return {'phase':phase,'anchor_world':point(ms['torso'],rig['anchor']),'visible_bbox':list(im.getchannel('A').getbbox()),'rgb_colors':len(np.unique(ar[:,:,:3][visible],axis=0)),'alpha_values':sorted(int(x) for x in np.unique(ar[:,:,3])),'joints_world':{name:point(ms[name],b['pivot']) for name,b in actual_rig['bones'].items()},'rotations_degrees':dict(pose),'projected_rotations_degrees':pose.front_rotations if pose.front_mix>0 else dict(pose),'projected_joint_pivots':{k:v['pivot'] for k,v in actual_rig['bones'].items()},'translations_pixels':pose.offsets,'expressions':pose.expressions,'view_projection':{'front_mix':pose.front_mix,'relaxed_mix':pose.relaxed_mix,'facing_angle':pose.facing_angle},'landmarks_world':{name:landmark(v) for name,v in rig.get('landmarks',{}).items()}}

def small_at_anchor(im,s,rig,skin):
 # Always sample the full 256 canvas with ONE fixed affine transform. No per-frame crop.
 coeff=(1/s,0,128-48/s,0,1/s,128-48/s)
 out=im.transform((96,96),Image.Transform.AFFINE,coeff,Image.Resampling.BICUBIC)
 return quantize_sprite(out,rig,skin)

def small_scale(frames,rig):
 bbox=[im.getchannel('A').getbbox() for images in frames.values() for im in images]
 union=[min(b[0] for b in bbox),min(b[1] for b in bbox),max(b[2] for b in bbox),max(b[3] for b in bbox)]
 initial=56/(union[3]-union[1]);best=None
 # Quantized alpha can move the discrete bounding box by one pixel. Search once over
 # ALL skins and poses; never rescale an individual frame or skin.
 for mul in np.linspace(.97,1.025,112):
  s=initial*float(mul);hi=max(small_at_anchor(im,s,rig,k).getbbox()[3]-small_at_anchor(im,s,rig,k).getbbox()[1] for key,images in frames.items() for im in images for k in [key[-1] if isinstance(key,tuple) else key])
  if hi==56:best=s;break
 if best is None:raise RuntimeError('Cannot fit the shared actual-size target to 56px.')
 return best,union

def gif_palette(frames):
 w=max(x.width for x in frames);atlas=Image.new('RGB',(w,sum(x.height for x in frames)))
 y=0
 for im in frames:atlas.paste(im,(0,y));y+=im.height
 fixed=ZONES+['#EAF4F1','#F4F7F2','#1D2938','#FFFFFF']
 q=atlas.quantize(colors=256-len(fixed),method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
 colors=[tuple(bytes.fromhex(x[1:])) for x in fixed]+[tuple(q.getpalette()[i:i+3]) for i in range(0,min(len(q.getpalette()),(256-len(fixed))*3),3)]
 return make_palette(['#%02X%02X%02X'%c for c in colors])

def gif_durations(n,fps=12):
 ticks=[math.floor(i*100/fps+.5) for i in range(n+1)]
 return [(ticks[i+1]-ticks[i])*10 for i in range(n)]

def save_gif(path,frames,loop=True,fps=12,durations=None):
 path.parent.mkdir(parents=True,exist_ok=True);pal=gif_palette(frames)
 out=[]
 for x in frames:
  rgb=x.convert('RGB');q=rgb.quantize(palette=pal,dither=Image.Dither.NONE);arr=np.array(q);source=np.array(rgb)
  for index,color in enumerate(ZONES):arr[np.all(source==np.array(tuple(bytes.fromhex(color[1:])),dtype='uint8'),axis=2)]=index
  q=Image.fromarray(arr,'P');q.putpalette(pal.getpalette());out.append(q)
 kwargs={'loop':0} if loop else {}
 out[0].save(path,save_all=True,append_images=out[1:],duration=durations or gif_durations(len(frames),fps),disposal=2,optimize=False,**kwargs)

def draw_text(im,xy,text,size=11,color='#EAF4F1',bold=False):
 draw=ImageDraw.Draw(im);draw.text(xy,text,fill=color,font=ImageFont.truetype(FONT_BOLD if bold else FONT,size))

def actual_panel(small,skin):
 im=Image.new('RGB',(600,128));d=ImageDraw.Draw(im)
 for j,(bg,label) in enumerate(zip(ZONES,ZONE_NAMES)):
  x=j*120;d.rectangle((x,0,x+119,127),fill=bg);draw_text(im,(x+9,7),f'{skin.upper()} / {label}',10,bold=True)
  im.paste(small,(x+12,22),small)
 return im

def single_dark(small):
 im=Image.new('RGB',(96,96),ZONES[2]);im.paste(small,(0,0),small);return im

def onion(images,path):
 out=Image.new('RGBA',(256,256),'#04070D')
 for im in images:
  layer=im.copy();layer.putalpha(layer.getchannel('A').point(lambda v:round(v*.15)));out=Image.alpha_composite(out,layer)
 d=ImageDraw.Draw(out);d.line((120,128,136,128),fill='#EF7857',width=1);d.line((128,120,128,136),fill='#EF7857',width=1);d.ellipse((125,125,131,131),outline='#EAF4F1',width=1)
 out.save(path);out.resize((1024,1024),Image.Resampling.NEAREST).save(path.with_name(path.stem+'_4x.png'))

def loop_self_check(rig,anim,write=True):
 p0=pose_at(0,rig,anim);p1=pose_at(1,rig,anim);eps=1e-5
 pose_error=max(abs(p0[k]-p1[k]) for k in p0)
 offset_error=max(abs(p0.offsets[k][j]-p1.offsets[k][j]) for k in p0 for j in range(2))
 v0={k:(pose_at(eps,rig,anim)[k]-pose_at(-eps,rig,anim)[k])/(2*eps) for k in p0}
 v1={k:(pose_at(1+eps,rig,anim)[k]-pose_at(1-eps,rig,anim)[k])/(2*eps) for k in p0}
 velocity_error=max(abs(v0[k]-v1[k]) for k in p0)
 anchors=[];root_motion=[];heads=[]
 for phase in np.linspace(0,1,257):
  pose=pose_at(float(phase),rig,anim)
  root_motion += [abs(pose[k]) for k in ['root','torso']]+[abs(v) for k in ['root','torso'] for v in pose.offsets[k]]
  for angle,scale,mirror in [(50,1,False),(65,.8,True),(35,.6,False)]:
   ms=matrices(pose,rig,angle,scale,mirror);a=point(ms['torso'],rig['anchor']);anchors.append(max(abs(a[i]-rig['anchor'][i]) for i in range(2)))
  heads.append(point(matrices(pose,rig)['head'],[128,66]))
 raster_equal=all(np.array_equal(np.array(render_frame(k,0,rig=rig,anim=anim)),np.array(render_frame(k,1,rig=rig,anim=anim))) for k in rig['skins'])
 head_range=np.ptp(np.array(heads),axis=0).tolist()
 result={'passed':pose_error<1e-9 and offset_error<1e-9 and velocity_error<1e-6 and max(anchors)<1e-9 and max(root_motion)==0 and raster_equal and (max(head_range)>.1 if anim['name']=='swim' else max(head_range)<1e-9),'animation':anim['name'],'phase_0_equals_1':pose_error<1e-9,'max_rotation_closure_error_degrees':pose_error,'max_offset_closure_error_pixels':offset_error,'max_velocity_closure_error_degrees_per_cycle':velocity_error,'max_chest_anchor_error_pixels':max(anchors),'max_root_or_chest_motion_channel':max(root_motion),'head_center_movement_range_source_pixels':head_range,'exact_phase_0_1_raster_match':raster_equal,'sampled_phase_points':257,'angle_scale_mirror_checks':[[50,1,False],[65,.8,True],[35,.6,False]],'interpolation':anim['interpolation'],'secondary_lag_frames':anim['secondary']['lag_frames'],'timeline_sha256':hashlib.sha256((BASE/f"rig/animations/{anim['name']}.json").read_bytes()).hexdigest()}
 if write:(BASE/f"preview/qa/{anim['name']}-self-check.json").write_text(json.dumps(result,indent=2)+'\n')
 if not result['passed']:raise RuntimeError('Renderer self-check failed: '+json.dumps(result))
 return result


def self_check(rig,anim,write=True):
 if anim['name'] in ['gulp','hit','lowair','out','turn']:
  anchors=[]
  for phase in np.linspace(0,1,129):
   p=pose_at(float(phase),rig,anim);a=point(matrices(p,rig)['torso'],rig['anchor']);anchors.append(max(abs(a[i]-rig['anchor'][i]) for i in range(2)))
  result={'animation':anim['name'],'fps':anim['fps'],'loop':anim['loop'],'max_chest_anchor_error_pixels':max(anchors),'events':anim.get('events',{}),'event_index_base':1,'projection':'authored body yaw/supine view; engine motion/VFX not baked','passed':max(anchors)<1e-9}
  if anim['name']=='hit':result['exact_last_to_swim0']=all(np.array_equal(np.array(render_frame(k,1,rig=rig,anim=anim)),np.array(render_frame(k,0,rig=rig,anim=load_animation('swim')))) for k in rig['skins']);result['passed'] &= result['exact_last_to_swim0']
  if anim['name']=='turn':result['front_alpha_symmetric']=all(np.array_equal(np.array(render_frame(k,1,rig=rig,anim=anim))[:,:,3],np.array(render_frame(k,1,rig=rig,anim=anim))[:,::-1,3]) for k in rig['skins']);result['passed'] &= result['front_alpha_symmetric']
  if anim['loop']:result['exact_loop_endpoint']=all(np.array_equal(np.array(render_frame(k,0,rig=rig,anim=anim)),np.array(render_frame(k,1,rig=rig,anim=anim))) for k in rig['skins']);result['passed'] &= result['exact_loop_endpoint']
  if write:(BASE/f"preview/qa/{anim['name']}-self-check.json").write_text(json.dumps(result,indent=2)+'\n')
  if not result['passed']:raise RuntimeError('Round3 selfcheck failed '+json.dumps(result))
  return result
 if anim['loop']:return loop_self_check(rig,anim,write)
 checks=[];rotation_error=0.;offset_error=0.;raster_match={}
 for endpoint,key in [(0,'from'),(1,'to')]:
  target=anim['transition'][key];other=load_animation(target['animation']);p=pose_at(endpoint,rig,anim);q=pose_at(target['phase'],rig,other)
  rotation_error=max(rotation_error,max(abs(p[k]-q[k]) for k in rig['bones']));offset_error=max(offset_error,max(abs(p.offsets[k][j]-q.offsets[k][j]) for k in rig['bones'] for j in range(2)))
  raster_match[key]={k:bool(np.array_equal(np.array(render_frame(k,endpoint,rig=rig,anim=anim)),np.array(render_frame(k,target['phase'],rig=rig,anim=other)))) for k in rig['skins']}
 anchors=[]
 for phase in np.linspace(0,1,257):
  p=pose_at(float(phase),rig,anim)
  for angle,scale,mirror in [(50,1,False),(65,.8,True),(35,.6,False)]:
   a=point(matrices(p,rig,angle,scale,mirror)['torso'],rig['anchor']);anchors.append(max(abs(a[i]-rig['anchor'][i]) for i in range(2)))
 result={'passed':rotation_error<1e-9 and offset_error<1e-9 and max(anchors)<1e-9 and all(all(v.values()) for v in raster_match.values()),'animation':anim['name'],'loop':False,'max_endpoint_rotation_error_degrees':rotation_error,'max_endpoint_offset_error_pixels':offset_error,'max_chest_anchor_error_pixels':max(anchors),'endpoint_raster_matches':raster_match,'transition':anim['transition'],'sample_phases':anim['sample_phases'],'claim':'C0 pose and pixel continuity at fixed endpoints; eased interior; no claim of C1 velocity matching between clips','timeline_sha256':hashlib.sha256((BASE/f"rig/animations/{anim['name']}.json").read_bytes()).hexdigest()}
 if write:(BASE/f"preview/qa/{anim['name']}-self-check.json").write_text(json.dumps(result,indent=2)+'\n')
 if not result['passed']:raise RuntimeError('Transition endpoint self-check failed: '+json.dumps(result))
 return result


def write_manifest(rig,anims,actual_scale):
 manifest={'schema_version':2,'revision':'round3_v4','status':'awaiting user confirmation; not integrated into game','canvas':[256,256],'anchor':[128,128],'fps':12,'nabo_target_height_px':56,'facing':'down-left','default_skin':'a','shared_rig':'rig/rig.json','skins':{k:{'name':v['name'],'slots':v['slots']} for k,v in rig['skins'].items()},'animations':{},'sprites':{},'preview_scale_to_actual':actual_scale,'history':'history/round2_v1/snapshot.json','previous_version':'history/round2_v3/snapshot.json','transition_policy':rig['transition_policy'],'preview_sequence':{'actual':'preview/dash_sequence_actual.gif','4x':'preview/dash_sequence_4x.gif','timeline':'preview/qa/dash-sequence.json'},'preview_sequences':{n:{'actual':f'preview/{n}_sequence_actual.gif','4x':f'preview/{n}_sequence_4x.gif','timeline':f'preview/qa/{n}-sequence.json'} for n in ['hit','turn']}}
 for name,anim in anims.items():
  mapping={k:[f'frames/{k}/{name}/{i+1:02}.png' for i in range(anim['frame_count'])] for k in rig['skins']}
  manifest['animations'][name]={'loop':anim['loop'],'fps':anim['fps'],'frame_count':anim['frame_count'],'timeline':f'rig/animations/{name}.json','frames':mapping['a'],'skin_frames':mapping,'events':anim.get('events',{}),'event_index_base':1,'transition':anim.get('transition'),'sample_phases':anim['sample_phases'],'preview_actual':f'preview/{name}_compare_actual.gif','preview_4x':f'preview/{name}_compare_4x.gif'}
 (BASE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')


def render_all(args):
 rig=load_rig();anims={name:load_animation(name) for name in ANIMATIONS}
 skins=list(rig['skins']) if args.skin=='all' else [args.skin]
 chosen=list(anims) if args.anim=='all' else [args.anim]
 variant='' if args.angle==50 and args.scale==1 and not args.mirror else f'variants/angle_{args.angle:g}_scale_{args.scale:g}'+('_mirror' if args.mirror else '')
 frame_root=BASE/'frames';preview_root=BASE/'preview'
 if variant:frame_root=frame_root/variant;preview_root=preview_root/variant
 allframes={(name,k):[render_frame(k,phase,args.angle,args.scale,args.mirror,rig,anim) for phase in anim['sample_phases']] for name,anim in anims.items() for k in rig['skins']}
 scale_to_actual=rig.get('fixed_actual_scale',0.25779258710765557);boxes=[im.getbbox() for images in allframes.values() for im in images];union=[min(x[0] for x in boxes),min(x[1] for x in boxes),max(x[2] for x in boxes),max(x[3] for x in boxes)]
 smalls={(name,k):[small_at_anchor(im,scale_to_actual,rig,k) for im in images] for (name,k),images in allframes.items()}
 panels={(name,k):[actual_panel(im,k) for im in images] for (name,k),images in smalls.items()}
 compare_by_anim={};compare4_by_anim={}
 for name in chosen:
  anim=anims[name];n=anim['frame_count']
  for skin in skins:
   out=frame_root/skin/name;out.mkdir(parents=True,exist_ok=True);pout=preview_root/skin;pout.mkdir(parents=True,exist_ok=True)
   infos=[]
   for i,im in enumerate(allframes[name,skin]):
    box=im.getbbox()
    if box[0]<=0 or box[1]<=0 or box[2]>=256 or box[3]>=256:raise RuntimeError(f'{name} skin {skin} frame {i+1} touches canvas edge; reduce --scale.')
    im.save(out/f'{i+1:02}.png');info=frame_info(im,anim['sample_phases'][i],rig,anim,args.angle,args.scale,args.mirror);info['file']=f'{i+1:02}.png';infos.append(info)
   heights=[im.getbbox()[3]-im.getbbox()[1] for im in smalls[name,skin]]
   actualdir=pout/f'{name}_actual_frames';actualdir.mkdir(exist_ok=True)
   meta={'revision':4,'skin':skin,'animation':name,'canvas':[256,256],'anchor':[128,128],'fps':anim['fps'],'frame_count':n,'loop':anim['loop'],'angle':args.angle,'scale':args.scale,'mirror':args.mirror,'shared_skeleton_sha256':hashlib.sha256(json.dumps(rig['bones'],sort_keys=True).encode()).hexdigest(),'timeline_sha256':hashlib.sha256((BASE/f'rig/animations/{name}.json').read_bytes()).hexdigest(),'frames':infos,'preview':{'scale_to_actual':scale_to_actual,'source_union_bbox':union,'actual_character_heights':heights,'actual_frame_canvas':[96,96],'actual_anchor':[48,48],'actual_frames_dir':str(actualdir.relative_to(BASE)),'actual_character_bboxes':[list(x.getbbox()) for x in smalls[name,skin]],'actual_boxes':[[j*120+12,22,96,96] for j in range(5)],'backgrounds':ZONES,'gif_durations_ms':gif_durations(n,anim['fps']),'exact_animation_fps':anim['fps'],'gif_cycle_ms':sum(gif_durations(n,anim['fps'])),'target_height_policy':'Retain previous round fixed affine scale across all nine clips and three skins; new poses may exceed nominal56px; per-frame heights reported; canvas96px. No per-frame or per-action fitting.'}}
   (out/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
   save_gif(pout/f'{name}_actual.gif',panels[name,skin],loop=anim['loop'],fps=anim['fps']);save_gif(pout/f'{name}_4x.gif',[single_dark(im).resize((384,384),Image.Resampling.NEAREST) for im in smalls[name,skin]],loop=anim['loop'],fps=anim['fps'])
   onion(allframes[name,skin],pout/f'{name}_onion.png')
   for i,im in enumerate(smalls[name,skin]):im.save(actualdir/f'{i+1:02}.png')
   print(f'{name} skin {skin}: {n} PNGs; actual heights {heights}; common actual scale {scale_to_actual:.9f}')
  if args.skin=='all':
   compare=[];compare4=[]
   for i in range(n):
    actual=Image.new('RGB',(600,384));large=Image.new('RGB',(1152,416),ZONES[2])
    for j,k in enumerate(rig['skins']):
     actual.paste(panels[name,k][i],(0,j*128));large.paste(single_dark(smalls[name,k][i]).resize((384,384),Image.Resampling.NEAREST),(j*384,32));draw_text(large,(j*384+18,8),f'{name.upper()} / {k.upper()} / v4',16,bold=True)
    compare.append(actual);compare4.append(large)
   save_gif(preview_root/f'{name}_compare_actual.gif',compare,loop=anim['loop'],fps=anim['fps']);save_gif(preview_root/f'{name}_compare_4x.gif',compare4,loop=anim['loop'],fps=anim['fps'])
   compare_by_anim[name]=compare;compare4_by_anim[name]=compare4
   sheet=Image.new('RGB',(n*256,840),'#04070D');onions=Image.new('RGB',(768,280),'#04070D')
   for row,k in enumerate(rig['skins']):
    for i,im in enumerate(allframes[name,k]):sheet.paste(im,(i*256,row*280+24),im);draw_text(sheet,(i*256+10,row*280+6),f'{name.upper()} / {k.upper()} / {i+1:02}',13,bold=True)
    onions.paste(Image.open(preview_root/k/f'{name}_onion.png').convert('RGB'),(row*256,24));draw_text(onions,(row*256+10,5),f'{name.upper()} / {k.upper()} / CHEST +',12,bold=True)
   sheet.save(preview_root/f'{name}_contact.png');onions.save(preview_root/f'{name}_compare_onion.png')
 if args.anim=='all' and args.skin=='all':
  actuals=[];large=[]
  for i in range(8):
   a=Image.new('RGB',(1200,384));a.paste(compare_by_anim['swim'][i],(0,0));a.paste(compare_by_anim['dash'][i%4],(600,0));actuals.append(a)
   b=Image.new('RGB',(2304,416));b.paste(compare4_by_anim['swim'][i],(0,0));b.paste(compare4_by_anim['dash'][i%4],(1152,0));large.append(b)
  save_gif(preview_root/'swim_dash_compare_actual.gif',actuals);save_gif(preview_root/'swim_dash_compare_4x.gif',large)
  entries=[{'animation':name,'frame_index':i} for name,repeats in [('swim',2),('dash_in',1),('dash',3),('dash_out',1),('swim',1)] for _ in range(repeats) for i in range(anims[name]['frame_count'])]
  seq_actual=[compare_by_anim[e['animation']][e['frame_index']] for e in entries];seq_large=[compare4_by_anim[e['animation']][e['frame_index']] for e in entries]
  save_gif(preview_root/'dash_sequence_actual.gif',seq_actual);save_gif(preview_root/'dash_sequence_4x.gif',seq_large)
  for k in rig['skins']:
   save_gif(preview_root/k/'dash_sequence_actual.gif',[panels[e['animation'],k][e['frame_index']] for e in entries])
   save_gif(preview_root/k/'dash_sequence_4x.gif',[single_dark(smalls[e['animation'],k][e['frame_index']]).resize((384,384),Image.Resampling.NEAREST) for e in entries])
  (preview_root/'qa').mkdir(exist_ok=True)
  (preview_root/'qa/dash-sequence.json').write_text(json.dumps({'fps':12,'frame_count':len(entries),'duration_seconds':len(entries)/12,'entries':entries,'durations_ms':gif_durations(len(entries)),'phase_policy':rig['transition_policy'],'paths':{'actual':'preview/dash_sequence_actual.gif','4x':'preview/dash_sequence_4x.gif'}},indent=2)+'\n')
  # New mixed-rate diagnostic sequences: logical frames are kept distinct with action/frame labels.
  from PIL import ImageOps
  hit_entries=[{'animation':a,'frame_index':i,'mirror':False,'fps':anims[a]['fps']} for a,inds in [('swim',range(8)),('hit',range(4)),('swim',list(range(1,8))+[0])] for i in inds]
  turn_entries=[{'animation':'swim','frame_index':i,'mirror':False,'fps':12} for i in range(8)]+[{'animation':'turn','frame_index':i,'mirror':False,'fps':24} for i in range(3)]+[{'animation':'turn','frame_index':i,'mirror':True,'fps':24} for i in [1,0]]+[{'animation':'swim','frame_index':i,'mirror':True,'fps':12} for i in list(range(1,8))+[0]]
  for label,items,loop in [('hit',hit_entries,True),('turn',turn_entries,False)]:
   time=Fraction(0);ticks=[0]
   for e in items:time+=Fraction(1,e['fps']);ticks.append(math.floor(time*100+Fraction(1,2)))
   durations=[(ticks[i+1]-ticks[i])*10 for i in range(len(items))];actualseq=[];largeseq=[]
   for j,e in enumerate(items):
    act=Image.new('RGB',(600,384));big=Image.new('RGB',(1152,416),ZONES[2])
    for row,k in enumerate(rig['skins']):
     small=smalls[e['animation'],k][e['frame_index']];small=ImageOps.mirror(small) if e['mirror'] else small
     panel=actual_panel(small,k)
     for zone in range(5):draw_text(panel,(zone*120+7,8),f"{k.upper()} {e['animation']} {e['frame_index']+1}",9,bold=True)
     act.paste(panel,(0,row*128));big.paste(single_dark(small).resize((384,384),Image.Resampling.NEAREST),(row*384,32));draw_text(big,(row*384+8,8),f"{k.upper()} / {e['animation']} {e['frame_index']+1} / {'R' if e['mirror'] else 'L'} / {e['fps']}fps",14,bold=True)
    actualseq.append(act);largeseq.append(big)
   save_gif(preview_root/f'{label}_sequence_actual.gif',actualseq,loop=loop,durations=durations);save_gif(preview_root/f'{label}_sequence_4x.gif',largeseq,loop=loop,durations=durations)
   (preview_root/f'qa/{label}-sequence.json').write_text(json.dumps({'entries':items,'durations_ms':durations,'frame_count':len(items),'duration_seconds':float(time),'duration_seconds_exact':str(time),'loop':loop,'phase_policy':'Fixed swim0 entry/recovery; post-hit and post-turn swim starts at frame2 to avoid repeated endpoint. Runtime blend required from arbitrary phase.','mirror_policy':'PIL.ImageOps.mirror of saved96px actual RGBA raster; engine mirror preview only, no duplicate source asset.'},indent=2)+'\n')
  # Fixed-scale, all-source-frame contacts for the five new clips.
  for name in ['gulp','hit','lowair','out','turn']:
   n=anims[name]['frame_count'];board=Image.new('RGB',(n*96,6*128));draw=ImageDraw.Draw(board)
   for row,(k,bg) in enumerate((k,bg) for k in rig['skins'] for bg in [ZONES[2],ZONES[4]]):
    for i,small in enumerate(smalls[name,k]):
     x=i*96;y=row*128;draw.rectangle((x,y,x+95,y+127),fill=bg);board.paste(small,(x,y+22),small);draw_text(board,(x+5,y+6),f'{k.upper()} {name} {i+1}',10)
   board.save(preview_root/f'qa/{name}-actual-contact.png')
  front_wordmark_mask(rig=rig).save(preview_root/'qa/turn-wordmark-mask.png')
  # Source-sized seam sheets show the last three and first three samples at all four joins.
  joins=[16,19,31,34];sheet=Image.new('RGB',(6*256,4*3*280),'#04070D')
  for block,j in enumerate(joins):
   for row,k in enumerate(rig['skins']):
    y=(block*3+row)*280
    for col,q in enumerate(range(j-3,j+3)):
     e=entries[q];im=allframes[e['animation'],k][e['frame_index']];sheet.paste(im,(col*256,y+24),im);draw_text(sheet,(col*256+8,y+6),f"{k.upper()} / seq {q+1} / {e['animation']} {e['frame_index']+1}",12,bold=True)
  sheet.save(preview_root/'dash_sequence_seams.png')
  if not variant:
   write_manifest(rig,anims,scale_to_actual)
   (BASE/'preview/swim_review.html').write_text('<!doctype html><meta charset="utf-8"><title>NABO Round3 v4</title><style>body{background:#101c2b;color:#eaf4f1;font:16px system-ui;padding:24px}img{image-rendering:pixelated;max-width:100%;height:auto}</style><h1>NABO round3 — v4 / awaiting user review</h1><p>Dark outlines. All3 skins. gulp3@12, hit4@12, lowair4@16, out6@12, turn3@24. Same fixed scale. Source/technical checks are not user approval.</p><h2>hit sequence</h2><img src="hit_sequence_4x.gif"><img src="hit_sequence_actual.gif"><h2>turn sequence</h2><img src="turn_sequence_4x.gif"><img src="turn_sequence_actual.gif"><h2>dash sequence</h2><img src="dash_sequence_4x.gif"><img src="dash_sequence_actual.gif"><h2>gulp</h2><img src="gulp_compare_4x.gif"><img src="gulp_compare_actual.gif"><h2>hit</h2><img src="hit_compare_4x.gif"><img src="hit_compare_actual.gif"><h2>lowair</h2><img src="lowair_compare_4x.gif"><img src="lowair_compare_actual.gif"><h2>out</h2><img src="out_compare_4x.gif"><img src="out_compare_actual.gif"><h2>turn</h2><img src="turn_compare_4x.gif"><img src="turn_compare_actual.gif">')

 if args.self_check:
  report={name:self_check(rig,anim) for name,anim in anims.items()}
  report['passed']=all(v['passed'] for v in report.values())
  (BASE/'preview/qa/renderer-self-check.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--skin',choices=['a','b','c','all'],default='all');parser.add_argument('--anim',choices=ANIMATIONS+['all'],default='all');parser.add_argument('--angle',type=float,default=50,help='Down-left dive angle below horizontal, degrees');parser.add_argument('--scale',type=float,default=1,help='Geometry scale around fixed chest on256 canvas');parser.add_argument('--mirror',action='store_true');parser.add_argument('--self-check',action='store_true')
 args=parser.parse_args()
 if not 0<args.scale<=3:parser.error('--scale must be >0 and <=3')
 render_all(args)

if __name__=='__main__':main()
