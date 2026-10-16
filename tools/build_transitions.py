#!/usr/bin/env python3
"""Author v3 fixed-phase dash transitions from preserved v2; no runtime engine edits."""
from pathlib import Path
import copy,json,importlib.util
BASE=Path(__file__).resolve().parents[1]
RIG=BASE/'rig';OLD=BASE/'history/round2_v2/rig'

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def author():
 rig=json.loads((OLD/'rig.json').read_text());dash=json.loads((OLD/'animations/dash.json').read_text())
 stable=['root','torso','neck','head','eyes','mouth','shoulder_near','shoulder_far','upper_arm_near','upper_arm_far','forearm_hand_near','forearm_hand_far','hand_near','hand_far','pelvis','thigh_near','thigh_far']
 first=dash['keyframes'][0]
 for f in dash['keyframes']:
  for bone in stable:
   if bone in rig['bones']:
    f['rotations'][bone]=first['rotations'][bone];f['translations'][bone]=copy.deepcopy(first['translations'][bone])
  f['label']='fixed head / shoulders / arms; alternating small ankle and shin flutter'
 dash['revision']=3;dash['notes']['dash_hold']='Head, neck, shoulders, arms, hands, pelvis and thighs are fixed. Only ankles/shins and garment ends move.'
 (RIG/'animations/dash.json').write_text(json.dumps(dash,ensure_ascii=False,indent=2)+'\n')
 rig['version']=3;rig['scope']='fixed-phase dash_in3 / dash4 / dash_out3 with swim8; awaiting user review'
 rig['animations']={name:f'animations/{name}.json' for name in ['swim','dash_in','dash','dash_out']}
 rig['action_draw_orders']['dash_in']=rig['draw_order'].copy();rig['action_draw_orders']['dash_out']=rig['draw_order'].copy()
 rig['transition_policy']={'entry_swim_phase':0,'entry_dash_phase':0,'exit_dash_phase':0,'exit_swim_phase':0,'sampling':'3 samples at u=0,1/3,2/3; hidden u=1 equals the next clip first frame','arbitrary_swim_phase':'Not solved by fixed PNGs. Runtime pose blending or phase gating is required; no engine changes in this delivery.'}
 rig['motion_policy']['dash_hold']=dash['notes']['dash_hold']
 (RIG/'rig.json').write_text(json.dumps(rig,ensure_ascii=False,indent=2)+'\n')
 render=module('dive_render_transition_author',BASE/'tools/render.py');ik=module('dive_rig_author_ik',BASE/'tools/revise_motion.py').ik
 swim=render.load_animation('swim');s=render.pose_at(0,rig,swim);d=render.pose_at(0,rig,dash)
 def blend(a,b,w):
  p={k:(1-w)*a[k]+w*b[k] for k in rig['bones']}
  t={k:[(1-w)*a.offsets[k][j]+w*b.offsets[k][j] for j in range(2)] for k in rig['bones']}
  return p,t
 brake=copy.deepcopy(dict(s))
 for parent,child,end,target,sign in [('upper_arm_near','forearm_hand_near',rig['bones']['hand_near']['pivot'],[106,24],1),('upper_arm_far','forearm_hand_far',rig['bones']['hand_far']['pivot'],[150,24],-1),('thigh_near','shin_foot_near',[111,205],[112,207],-1),('thigh_far','shin_foot_far',[153,202],[144,207],1)]:
  brake[parent],brake[child]=ik(rig,parent,child,end,target,sign)
 brake['foot_near']=4;brake['foot_far']=-4;brake['head']=-2
 for name,a,b in [('dash_in',s,d),('dash_out',d,s)]:
  keys=[]
  for i,u in enumerate([0,1/3,2/3,1]):
   w=u*u*(3-2*u);rot,offset=blend(a,b,w)
   if name=='dash_out' and i in (1,2):
    amount=[0,.65,.24,0][i]
    for k in ['upper_arm_near','upper_arm_far','forearm_hand_near','forearm_hand_far','thigh_near','thigh_far','shin_foot_near','shin_foot_far','foot_near','foot_far','head']:
     rot[k]=(1-amount)*rot[k]+amount*brake[k]
    for k,gain in [('cloth_waist_near',4),('cloth_waist_far',6),('cloth_collar',5)]:rot[k]+=gain*amount
   mix=([0,.08,.65,1] if name=='dash_in' else [1,.94,.45,0])[i]
   keys.append({'phase':u,'label':('gather arms / tighten legs / cloth follows' if name=='dash_in' else 'small braking flare / recover swim glide'),'rotations':rot,'translations':offset,'cloth_mix':mix})
  source,target=('swim','dash') if name=='dash_in' else ('dash','swim')
  anim={'name':name,'revision':3,'fps':12,'frame_count':3,'loop':False,'duration_seconds':.25,'sample_phases':[0,1/3,2/3],'interpolation':'clamped shape-preserving cubic Hermite; eased fixed-phase transition; C0 raster-matched hidden endpoint','keyframes':keys,'secondary':{'mode':'baked garment rotation with delayed SVG contour morph'},'skin_invariant':True,'transition':{'from':{'animation':source,'phase':0},'to':{'animation':target,'phase':0},'fixed_phase_only':True,'hidden_endpoint_phase':1,'endpoint_not_exported':'Next clip first frame supplies u=1 after the three output samples.'},'notes':rig['transition_policy']}
  (RIG/f'animations/{name}.json').write_text(json.dumps(anim,ensure_ascii=False,indent=2)+'\n')
 print('Authored v3: stable dash and fixed-phase dash_in3/dash_out3; swim source unchanged.')

if __name__=='__main__':author()
