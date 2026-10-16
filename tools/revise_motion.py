#!/usr/bin/env python3
"""Author round-two revision: linked neck, shoulder recovery, ankle articulation, dash."""
from pathlib import Path
import json, math, copy, xml.etree.ElementTree as ET
BASE=Path(__file__).resolve().parents[1]
RIG=BASE/'rig'
NS='http://www.w3.org/2000/svg';ET.register_namespace('',NS)

def save_svg(path,children):
 root=ET.Element('{'+NS+'}svg',{'width':'256','height':'256','viewBox':'0 0 256 256'})
 for x in children:root.append(copy.deepcopy(x))
 path.write_text(ET.tostring(root,encoding='unicode'))

def path(d,fill,stroke='#1D2938',width=2.8):
 return ET.Element('{'+NS+'}path',{'d':d,'fill':fill,'stroke':stroke,'stroke-width':str(width),'stroke-linejoin':'round','stroke-linecap':'round'})

def ik(rig,parent,child,end,target,sign):
 s=rig['bones'][parent]['pivot'];e=rig['bones'][child]['pivot']
 a=[e[i]-s[i] for i in range(2)];b=[end[i]-e[i] for i in range(2)]
 l1=math.hypot(*a);l2=math.hypot(*b);dx,dy=target[0]-s[0],target[1]-s[1]
 dist=max(abs(l1-l2)+.05,min(l1+l2-.05,math.hypot(dx,dy)))
 bend=sign*math.acos(max(-1,min(1,(dist*dist-l1*l1-l2*l2)/(2*l1*l2))))
 theta=math.atan2(dy,dx)-math.atan2(l2*math.sin(bend),l1+l2*math.cos(bend))
 wrap=lambda a:(a+180)%360-180
 bind1=math.degrees(math.atan2(a[1],a[0]));bind2=wrap(math.degrees(math.atan2(b[1],b[0]))-bind1)
 return [wrap(math.degrees(theta)-bind1),wrap(math.degrees(bend)-bind2)]

def affine_projection(children,origin,end,new_origin,factor):
 dx,dy=end[0]-origin[0],end[1]-origin[1];length=math.hypot(dx,dy);ux,uy=dx/length,dy/length
 a=1+(factor-1)*ux*ux;b=(factor-1)*ux*uy;d=1+(factor-1)*uy*uy
 tx=new_origin[0]-a*origin[0]-b*origin[1];ty=new_origin[1]-b*origin[0]-d*origin[1]
 group=ET.Element('{'+NS+'}g',{'transform':f'matrix({a} {b} {b} {d} {tx} {ty})'})
 for el in children:group.append(copy.deepcopy(el))
 return [group]

def author():
 old=BASE/'history/round2_v1/rig';rig=json.loads((old/'rig.json').read_text());bones=rig['bones']
 for side,x in [('near',107),('far',149)]:
  bones['shoulder_'+side]={'parent':'torso','pivot':[x,121]}
  bones['upper_arm_'+side]['parent']='shoulder_'+side
 bones['pelvis']={'parent':'torso','pivot':[128,159]}
 for side in ['near','far']:bones['thigh_'+side]['parent']='pelvis'
 bones['head']['parent']='neck'
 bones['foot_near']={'parent':'shin_foot_near','pivot':[111,205]};bones['foot_far']={'parent':'shin_foot_far','pivot':[153,202]}
 bones['hand_near']={'parent':'forearm_hand_near','pivot':[78,103]};bones['hand_far']={'parent':'forearm_hand_far','pivot':[188,119]}
 projection=2.2;arm_bind={}
 for side in ['near','far']:
  shoulder=bones['upper_arm_'+side]['pivot'];elbow=bones['forearm_hand_'+side]['pivot'];wrist=bones['hand_'+side]['pivot']
  new_elbow=[shoulder[j]+projection*(elbow[j]-shoulder[j]) for j in range(2)]
  new_wrist=[new_elbow[j]+projection*(wrist[j]-elbow[j]) for j in range(2)]
  arm_bind[side]=(shoulder,elbow,wrist,new_elbow,new_wrist)
  bones['forearm_hand_'+side]['pivot']=new_elbow;bones['hand_'+side]['pivot']=new_wrist
 # Split the approved shin/boot drawing without repainting or changing its colors.
 for skin in 'abc':
  slots=rig['skins'][skin]['slots']
  for side in ['near','far']:
   src=ET.parse(old/f'skins/{skin}/shin_foot_{side}.svg').getroot();g=list(src)[1] if list(src)[0].tag.endswith('title') else list(src)[0]
   children=list(g);shin=children[:3]+(children[6:] if len(children)>6 else []);shoe=children[3:6]
   save_svg(RIG/f'skins/{skin}/shin_foot_{side}.svg',shin)
   save_svg(RIG/f'skins/{skin}/foot_{side}.svg',shoe);slots['foot_'+side]=f'skins/{skin}/foot_{side}.svg'
  for side in ['near','far']:
   src=ET.parse(old/f'skins/{skin}/forearm_hand_{side}.svg').getroot();g=list(src)[1] if list(src)[0].tag.endswith('title') else list(src)[0];children=list(g)
   shoulder,elbow,wrist,new_elbow,new_wrist=arm_bind[side]
   save_svg(RIG/f'skins/{skin}/forearm_hand_{side}.svg',affine_projection(children[:3],elbow,wrist,new_elbow,projection))
   # Palms keep their original size; only their bind position changes.
   save_svg(RIG/f'skins/{skin}/hand_{side}.svg',affine_projection(children[3:],wrist,[wrist[0]+1,wrist[1]],new_wrist,1));slots['hand_'+side]=f'skins/{skin}/hand_{side}.svg'
   upper=ET.parse(old/f'skins/{skin}/upper_arm_{side}.svg').getroot();part=list(upper)[1] if list(upper)[0].tag.endswith('title') else list(upper)[0]
   save_svg(RIG/f'skins/{skin}/upper_arm_{side}.svg',affine_projection(list(part),shoulder,elbow,shoulder,projection))
  # Streamlined garment poses use the same attachment slots and immutable palette.
  white='#F4F7F2';w1='#CDDDE2';w2='#8EA9B7';blue='#2670B5';b1='#175383';b2='#113958'
  shapes={}
  if skin=='a':
   shapes['cloth_waist_near']=[path('M106 153L120 160L112 185L102 181L105 165Z',white),path('M108 165L115 163L109 181L104 179Z',w1,'none',0),path('M108 176L112 174L110 184L104 181Z',w2,'none',0)]
   shapes['cloth_waist_far']=[path('M137 152L149 154L155 184L144 183L139 166Z',white),path('M144 158L150 161L153 181L146 180Z',w1,'none',0),path('M148 174L153 175L154 183L147 182Z',w2,'none',0)]
  if skin=='b':shapes['cloth_waist_far']=[path('M144 151L153 152Q157 171 158 192L150 189Q147 168 144 151Z',white),path('M149 156L152 157L157 190L153 188Z',w1,'none',0),path('M153 181L157 183L158 192L154 190Z',w2,'none',0)]
  if skin=='c':shapes['cloth_collar']=[path('M144 114L154 117Q160 138 164 163L153 160Q149 135 144 114Z',blue),path('M149 118L154 121L162 160L157 158Z',b1,'none',0),path('M157 147L162 151L164 163L158 161Z',b2,'none',0)]
  rig['skins'][skin]['animation_overrides']={'dash':{}}
  for slot,content in shapes.items():
   rel=f'skins/{skin}/dash_{slot}.svg';save_svg(RIG/rel,content);rig['skins'][skin]['animation_overrides']['dash'][slot]=rel
 order=rig['draw_order'];order.insert(order.index('shin_foot_far')+1,'foot_far');order.insert(order.index('shin_foot_near')+1,'foot_near')
 # Foreground near forearm gives the recovery and dash palm overlap a readable depth cue.
 order+=['hand_far','hand_near']
 rig['action_draw_orders']={'swim':order.copy(),'dash':order.copy()}
 rig['version']=2;rig['scope']='round 2 revision / swim and dash only; waiting for user animation confirmation'
 rig['animations']={'swim':'animations/swim.json','dash':'animations/dash.json'}
 rig['motion_policy']={'root':'fixed','torso':'fixed chest at128,128; no global tilt, translation, squash','local_motion':'neck -> head chain; shoulder offsets <=3px; pelvis rotation <=2deg; hip/knee/ankle links','constant_arm_lengths_within_revision':True,'arm_bind_projection_revision':2.2,'dash_projection':'Head/costume/hand shape and limb width unchanged. Fixed arm centerline projection calibrated once for overhead reach, shared by all skins and both actions. No per-frame stretch.'}
 rig['landmarks']={'chest':{'bone':'torso','point':[128,128]},'head_center':{'bone':'head','point':[128,66]},'neck_head_join':{'bone':'head','point':[128,104]},'wrist_near':{'bone':'hand_near','point':bones['hand_near']['pivot']},'wrist_far':{'bone':'hand_far','point':bones['hand_far']['pivot']},'ankle_near':{'bone':'foot_near','point':[111,205]},'ankle_far':{'bone':'foot_far','point':[153,202]}}
 (RIG/'rig.json').write_text(json.dumps(rig,ensure_ascii=False,indent=2)+'\n')
 arm_near=[[118,13],[51,65],[116,114],[114,50],[118,13],[119,12],[118,13],[118,13]]
 arm_far=[[138,13],[205,65],[140,114],[142,50],[138,13],[137,12],[138,13],[138,13]]
 # Keep the legs long during the pull. Heels recover only while hands return forward.
 ankle_near=[[121,207],[121,207],[121,207],[113,194],[119,188],[102,204],[119,207],[121,207]]
 ankle_far=[[135,207],[135,207],[135,207],[143,194],[137,188],[154,204],[137,207],[135,207]]
 heads=[-4,-1,6,3,-4,-6,-5,-4];necks=[-.5,0,1,.5,-.5,-.8,-.6,-.5]
 pelvis=[0,0,.2,1.3,1.8,-.9,-.5,0];ankles_n=[-4,-4,-4,10,27,13,-5,-4];ankles_f=[4,4,4,-10,-27,-13,5,4]
 def make_anim(name,n):
  frames=[]
  for i in range(n):
   rot={k:0.0 for k in bones};trans={k:[0.0,0.0] for k in bones}
   if name=='swim':
    an,af=arm_near[i],arm_far[i];ln,lf=ankle_near[i],ankle_far[i]
    rot['head']=heads[i];rot['neck']=necks[i];rot['pelvis']=pelvis[i]
    rot['shoulder_near']=[0,-.6,1.5,.7,-.3,-.6,-.2,0][i];rot['shoulder_far']=[0,.6,-1.5,-.7,.3,.6,.2,0][i]
    sy=[-.8,-.5,-1.4,-2.8,-2.1,-1.0,-.8,-.8][i];trans['shoulder_near']=[-.3,sy];trans['shoulder_far']=[.3,sy]
    trans['neck']=[0,[-.3,-.5,-1.2,-.6,0,-.2,-.3,-.3][i]]
    rot['foot_near']=ankles_n[i];rot['foot_far']=ankles_f[i]
    label=['streamline glide','out-sweep / legs long','insweep / small head lift','direct arm recovery / heels recover','arms long / heels set / feet turn out','backward whip kick','squeeze feet together / head neutral','short glide / settle'][i]
   else:
    an=[126,8];af=[130,8];ln=[123,207];lf=[133,207]
    tension=[0,.6,0,-.6][i];rot['head']=-4+tension;rot['neck']=-.5+.2*tension;rot['pelvis']=.3*tension
    trans['shoulder_near']=[.5,-2.6-.5*tension];trans['shoulder_far']=[-.5,-2.6-.5*tension];trans['neck']=[0,.5]
    rot['shoulder_near']=.2*tension;rot['shoulder_far']=-.2*tension
    rot['foot_near']=-5+12*tension;rot['foot_far']=5-12*tension
    label=['tight streamline / palms overlap','water pressure / slight neck follow','held extension / tension','settle / cloth follows'][i]
   for parent,child,end,target,sign in [('upper_arm_near','forearm_hand_near',bones['hand_near']['pivot'],an,1),('upper_arm_far','forearm_hand_far',bones['hand_far']['pivot'],af,-1),('thigh_near','shin_foot_near',[111,205],ln,-1),('thigh_far','shin_foot_far',[153,202],lf,1)]:
    a,c=ik(rig,parent,child,end,target,sign);rot[parent]=round(a,6);rot[child]=round(c,6)
   if name=='dash':
    rot['shin_foot_near']+=3*tension;rot['shin_foot_far']-=3*tension
   frames.append({'phase':i/n,'label':label,'rotations':rot,'translations':trans})
  secondary={'driver':[0,4,14,11,-9,-13,-5,-1] if name=='swim' else [0,1.2,0,-1.2],'lag_frames':1.25 if name=='swim' else .75,'nodes':{'cloth_waist_near':{'gain':.6,'phase_offset':0},'cloth_waist_far':{'gain':.85,'phase_offset':0},'cloth_collar':{'gain':.7,'phase_offset':0}}}
  return {'name':name,'revision':2,'fps':12,'frame_count':n,'loop':True,'duration_seconds':n/12,'sample_phases':[i/n for i in range(n)],'interpolation':'C1 periodic Hermite / slope-limited tangents; no uniform pendulum or duplicate end frame','keyframes':frames,'secondary':secondary,'skin_invariant':True,'notes':rig['motion_policy'],'references':['https://www.usms.org/fitness-and-training/guides/breaststroke/timing','https://www.usms.org/fitness-and-training/guides/breaststroke/pull','https://www.usms.org/fitness-and-training/guides/breaststroke/kick','https://www.usms.org/fitness-and-training/guides/breaststroke/body-position']}
 for name,n in [('swim',8),('dash',4)]:
  anim=make_anim(name,n);(RIG/f'animations/{name}.json').write_text(json.dumps(anim,ensure_ascii=False,indent=2)+'\n')
  print(name,'head angles',[f['rotations']['head'] for f in anim['keyframes']])
  print(name,'upper near',[round(f['rotations']['upper_arm_near'],1) for f in anim['keyframes']])
  print(name,'forearm near',[round(f['rotations']['forearm_hand_near'],1) for f in anim['keyframes']])
 print('Shared bones',len(bones),'slots',len(order),'head/costume/palms preserved; fixed arm projection revised, ankles articulated, streamline cloth authored.')

if __name__=='__main__':author()
