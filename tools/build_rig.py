#!/usr/bin/env python3
"""Extract approved head/garments and author reusable limb segments. Only round two."""
from pathlib import Path
import sys, importlib.util, json, xml.etree.ElementTree as ET, math, hashlib
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('approved_design',BASE/'design/build_designs.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
RIG=BASE/'rig'

def svg_file(rel,body):
 p=RIG/rel;p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><title>NABO shared-rig component / '+rel+'</title>'+body+'</svg>')
 return rel

def serialize(e):return ET.tostring(e,encoding='unicode')
def shape(d,fill,sw=2.8,stroke='ink'):return b.path(d,fill,sw,stroke)
def shadow(d,fill):return b.path(d,fill,0,'none')


def main():
 head=ET.fromstring(b.head(False));expr=head.find("./g[@id='face-expression']")
 eyes=ET.Element('g',{'id':'eyes-neutral'});mouth=ET.Element('g',{'id':'mouth-neutral'})
 children=list(expr)
 for el in children[:-1]:eyes.append(el)
 mouth.append(children[-1]);head.remove(expr)
 common={
  'head':svg_file('common/head.svg',serialize(head)),
  'eyes':svg_file('common/eyes_neutral.svg',serialize(eyes)),
  'mouth':svg_file('common/mouth_neutral.svg',serialize(mouth)),
 }
 # All coordinates stay in the approved 256px bind space; renderer composes joint matrices.
 bones={
  'root':{'parent':None,'pivot':[128,128]},
  'torso':{'parent':'root','pivot':[128,128]},
  'neck':{'parent':'torso','pivot':[128,110]},
  'head':{'parent':'torso','pivot':[128,104]},
  'eyes':{'parent':'head','pivot':[128,80]},
  'mouth':{'parent':'head','pivot':[124,99]},
  'upper_arm_near':{'parent':'torso','pivot':[107,121]},
  'forearm_hand_near':{'parent':'upper_arm_near','pivot':[84,131]},
  'upper_arm_far':{'parent':'torso','pivot':[149,121]},
  'forearm_hand_far':{'parent':'upper_arm_far','pivot':[169,142]},
  'thigh_near':{'parent':'torso','pivot':[118,164]},
  'shin_foot_near':{'parent':'thigh_near','pivot':[108,187]},
  'thigh_far':{'parent':'torso','pivot':[138,164]},
  'shin_foot_far':{'parent':'thigh_far','pivot':[156,183]},
  'cloth_waist_near':{'parent':'torso','pivot':[110,154]},
  'cloth_waist_far':{'parent':'torso','pivot':[144,154]},
  'cloth_collar':{'parent':'torso','pivot':[146,116]},
 }
 layers=['cloth_waist_near','cloth_waist_far','cloth_collar','upper_arm_far','forearm_hand_far','thigh_far','shin_foot_far','thigh_near','shin_foot_near','neck','torso','upper_arm_near','forearm_hand_near','head','eyes','mouth']
 skins={}
 for skin in 'abc':
  root=ET.fromstring('<g>'+b.body(skin,False)+'</g>')
  nodes={x.get('id'):x for x in root}
  common['neck']=svg_file('common/neck.svg',serialize(nodes['neck']))
  assets=dict(common)
  assets['torso']=svg_file(f'skins/{skin}/torso.svg',serialize(nodes['torso']))
  floatnames={'a':{'cloth_waist_near':'short-coat-tail','cloth_waist_far':'floating-coat-tail'},'b':{'cloth_waist_far':'floating-rescue-ribbon'},'c':{'cloth_collar':'floating-collar-tab'}}[skin]
  for slot in ['cloth_waist_near','cloth_waist_far','cloth_collar']:
   assets[slot]=svg_file(f'skins/{skin}/{slot}.svg',serialize(nodes[floatnames[slot]])) if slot in floatnames else None
  sleeve='white' if skin!='c' else 'mint';sleeve1='w1' if skin!='c' else 'm1';sleeve2='w2' if skin!='c' else 'm2'
  suit={'a':'navy','b':'coral','c':'mint'}[skin];s1={'a':'n1','b':'c1','c':'m1'}[skin];s2={'a':'n2','b':'c2','c':'m2'}[skin]
  segments={}
  segments['upper_arm_near']=shape('M108 112Q100 111 92 118L79 124Q75 130 81 136Q87 142 94 136L112 128Z',sleeve)+shadow('M82 127L107 116L110 123L89 136Q83 137 82 127Z',sleeve1)+shadow('M83 133L93 129L110 120L112 128L94 136Q89 140 83 136Z',sleeve2)
  segments['forearm_hand_near']=shape('M78 136Q75 130 74 120L70 108L83 102L92 127Q97 138 87 141Q81 141 78 136Z',sleeve)+shadow('M78 114L83 111L90 128Q94 135 88 138L83 136Z',sleeve1)+shadow('M84 126L91 126Q97 138 87 141L81 137L88 135Z',sleeve2)+shape('M71 111L68 103Q65 96 72 93Q79 89 84 96L88 106Q88 110 81 113Z','skin')+shadow('M81 96Q85 99 87 106L82 111L79 109L81 103Z','s1')
  segments['upper_arm_far']=shape('M144 115Q152 111 159 119L176 134Q181 141 174 148Q167 154 161 147L145 132Z',sleeve)+shadow('M151 119L173 138L176 143L170 148L151 131Z',sleeve1)+shadow('M168 137L177 139Q179 145 173 149L166 146Z',sleeve2)
  segments['forearm_hand_far']=shape('M162 137L180 116L192 124L177 149Q172 156 166 150Q162 147 162 137Z',sleeve)+shadow('M168 143L187 120L192 124L176 149L170 152Z',sleeve1)+shadow('M175 138L189 122L192 124L177 149L170 152Z',sleeve2)+shape('M181 124L179 116Q177 108 184 105Q191 103 195 111L196 122L190 128Z','skin')+shadow('M190 108L195 113L196 122L190 127L187 124L191 119Z','s1')
  segments['thigh_near']=shape('M109 157Q117 154 125 161L121 181Q119 194 110 196Q99 196 98 186L103 168Z',suit)+shadow('M114 161L121 165L114 186L106 193L101 188L105 174Z',s1)+shadow('M118 173L121 174L118 188Q116 196 107 194L106 189L112 185Z',s2)
  segments['shin_foot_near']=shape('M99 183Q106 178 115 184L120 204Q122 213 114 216Q104 220 101 210Z',suit)+shadow('M107 184L114 185L119 204L114 212L109 211Z',s1)+shadow('M114 192L118 199L119 207L114 213L111 209Z',s2)
  segments['shin_foot_near']+=shape('M101 204L119 204L124 216Q119 225 103 223L98 217Z','white')+shadow('M100 216Q112 223 123 215L122 220Q112 226 103 223Z','w1')+shadow('M103 220Q113 224 122 218L121 222Q112 226 103 223Z','w2')
  segments['thigh_far']=shape('M129 162Q137 155 146 159L161 175Q168 182 161 190Q155 198 147 191L133 178Z',suit)+shadow('M140 162L145 162L160 178Q165 184 157 191L152 189L153 182Z',s1)+shadow('M153 175L161 179Q166 184 160 190L155 193L151 187L157 184Z',s2)
  segments['shin_foot_far']=shape('M148 180Q156 175 164 182L161 205Q159 215 150 213Q143 212 143 204Z',suit)+shadow('M156 181L163 184L159 204L151 211L148 208Z',s1)+shadow('M158 190L162 188L160 205L152 212L150 207L156 202Z',s2)
  segments['shin_foot_far']+=shape('M144 200L161 202L169 214Q162 224 148 221L141 214Z','white')+shadow('M143 212Q157 221 167 212L169 216Q159 225 148 221Z','w1')+shadow('M149 219Q158 221 168 214L168 218Q159 224 149 221Z','w2')
  if skin=='c':
   segments['shin_foot_near']+=shape('M100 198L119 197L121 205L102 209Z','navy',1.8)
   segments['shin_foot_far']+=shape('M144 195L162 196L162 203L143 204Z','navy',1.8)
  for name,content in segments.items():assets[name]=svg_file(f'skins/{skin}/{name}.svg',b.group(name,content))
  keys=b.set_sprite_palette(skin)
  skins[skin]={'name':{'a':'白褂潜行','b':'珊瑚救援','c':'薄荷深潜'}[skin],'design_reference':f'../design/option_{skin}.png','palette':{k:b.P[k] for k in keys},'slots':assets}
 rig={'version':1,'scope':'round 2 / swim only; three retained skins','canvas':[256,256],'anchor':[128,128],'fps':12,'standard_angle_degrees':50,'facing':'down-left','coordinate_system':'Each SVG uses the same absolute 256x256 bind coordinates. Parent world matrix times rotation about bind pivot. Root: T(anchor) R(-90-angle) S(scale) T(-anchor).','bones':bones,'draw_order':layers,'outline':{'rgb':b.P['rim'],'source_stroke_width':12,'type':'hard vector union underlay, no glow'},'skins':skins,'animations':{'swim':'animations/swim.json'}}
 (RIG/'rig.json').write_text(json.dumps(rig,ensure_ascii=False,indent=2)+'\n')
 # Targets express a breaststroke: outward pull, recovery, then frog kick. IK is baked
 # ONCE into a shared rotation timeline; skin selection never influences kinematics.
 targets={
  'arm_near':[[88,78],[59,105],[71,145],[92,145],[80,100],[88,78],[88,78],[88,78]],
  'arm_far':[[169,78],[198,105],[185,145],[164,145],[177,100],[169,78],[169,78],[169,78]],
  'leg_near':[[118,214],[118,214],[104,199],[99,184],[82,194],[89,208],[115,214],[118,214]],
  'leg_far':[[138,214],[138,214],[152,199],[157,184],[174,194],[167,208],[141,214],[138,214]],
 }
 def ik(shoulder,elbow,end,target,sign):
  v1=[elbow[i]-shoulder[i] for i in range(2)];v2=[end[i]-elbow[i] for i in range(2)]
  l1=math.hypot(*v1);l2=math.hypot(*v2);dx=target[0]-shoulder[0];dy=target[1]-shoulder[1]
  dist=max(abs(l1-l2)+.01,min(l1+l2-.01,math.hypot(dx,dy)))
  bend=sign*math.acos(max(-1,min(1,(dist*dist-l1*l1-l2*l2)/(2*l1*l2))))
  theta=math.atan2(dy,dx)-math.atan2(l2*math.sin(bend),l1+l2*math.cos(bend))
  wrap=lambda a:(a+180)%360-180
  bind1=math.degrees(math.atan2(v1[1],v1[0]));bind2=wrap(math.degrees(math.atan2(v2[1],v2[0]))-bind1)
  return [round(wrap(math.degrees(theta)-bind1),6),round(wrap(math.degrees(bend)-bind2),6)]
 chains=[('arm_near','upper_arm_near','forearm_hand_near',[78,103],1),('arm_far','upper_arm_far','forearm_hand_far',[188,119],-1),('leg_near','thigh_near','shin_foot_near',[111,211],-1),('leg_far','thigh_far','shin_foot_far',[153,211],1)]
 frames=[{'phase':i/8,'label':['reach / glide','out-sweep','in-sweep / heel recovery','hand recovery / coil','forward send / feet open','frog kick','close legs','glide / settle'][i],'rotations':{k:0.0 for k in bones}} for i in range(8)]
 for targetkey,parent,child,end,sign in chains:
  for i,target in enumerate(targets[targetkey]):
   a,c=ik(bones[parent]['pivot'],bones[child]['pivot'],end,target,sign);frames[i]['rotations'][parent]=a;frames[i]['rotations'][child]=c
 # Drive the tail slots from a shared, periodic effort curve with 1.5-frame lag.
 anim={'name':'swim','fps':12,'frame_count':8,'loop':True,'duration_seconds':8/12,'sample_phases':[i/8 for i in range(8)],'interpolation':'periodic cubic Hermite with shared Catmull-Rom endpoint tangents (C1); phase 1 equals phase 0, not exported twice','keyframes':frames,'secondary':{'driver':[0,16,10,-8,-14,0,8,3],'lag_frames':1.5,'nodes':{'cloth_waist_near':{'gain':.7,'phase_offset':.08},'cloth_waist_far':{'gain':1.0,'phase_offset':0},'cloth_collar':{'gain':.9,'phase_offset':.04}}},'skin_invariant':True,'notes':'No root translation, body tilt, squash, glow, bubbles, or mirrored frames baked in. Head and chest remain stable.'}
 (RIG/'animations/swim.json').write_text(json.dumps(anim,ensure_ascii=False,indent=2)+'\n')
 print('Shared skeleton:',len(bones),'bones;',len(layers),'draw slots; skins:',','.join(skins))
 print('SVGs:',len(list(RIG.rglob('*.svg'))),'shared animation: 8 samples / 12 fps')

if __name__=='__main__':main()
