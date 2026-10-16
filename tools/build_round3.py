#!/usr/bin/env python3
"""Author the updated round-three scope without changing legacy clip timelines."""
from pathlib import Path
import json,copy,importlib.util,hashlib
BASE=Path(__file__).resolve().parents[1];RIG=BASE/'rig';OLD=BASE/'history/round2_v3/rig'
def module(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def author():
 rig=json.loads((OLD/'rig.json').read_text())
 for name in ['swim','dash_in','dash','dash_out']:
  assert (RIG/f'animations/{name}.json').read_bytes()==(OLD/f'animations/{name}.json').read_bytes(),f'Legacy {name} timeline differs; stop instead of overwriting.'
 rig['version']=4;rig['scope']='round3 updated prototype brief; old and new animations awaiting user review; no integration claimed'
 rig['bones']['mouth_bubbles']={'parent':'head','pivot':[124,99]}
 rig['draw_order'].insert(rig['draw_order'].index('mouth')+1,'mouth_bubbles')
 for order in rig['action_draw_orders'].values():order.insert(order.index('mouth')+1,'mouth_bubbles')
 for skin in rig['skins'].values():skin['slots']['mouth_bubbles']=None;skin['palette']['rim']='#101E34'
 rig['outline']['rgb']='#101E34';rig['outline']['type']='hard dark silhouette underlay; recolor only for legacy four actions; no light rim'
 rig['fixed_actual_scale']=0.25779258710765557
 rig['expressions']=json.loads((RIG/'common/expressions/index.json').read_text())['assets']
 rig['front_views']={'streamline':json.loads((RIG/'common/front/slots.json').read_text()),'relaxed':json.loads((RIG/'common/front/slots_relaxed.json').read_text())}
 rig['front_views']['streamline']['front_pivots']['mouth_bubbles']=[128,99];rig['front_views']['relaxed']['front_pivots']['mouth_bubbles']=[128,99]
 rig['animations'].update({n:f'animations/{n}.json' for n in ['gulp','hit','lowair','out','turn']})
 rig['round3_contract']={'legacy_change':'outline RGB only; source timelines and original24 bone definitions preserved','fps':{'gulp':12,'hit':12,'lowair':16,'out':12,'turn':24},'user_acceptance':'pending for all animation versions','optional_not_made':['nearmiss','record'],'projection':'Front yaw / supine body performance uses authored SVG view variants with projected joint coordinates, not an engine tilt/squash effect.'}
 (RIG/'rig.json').write_text(json.dumps(rig,ensure_ascii=False,indent=2)+'\n')
 r=module('dive_round3_renderer_author',BASE/'tools/render.py');ik=module('dive_round3_ik',BASE/'tools/revise_motion.py').ik
 swim=r.load_animation('swim');base=r.pose_at(0,rig,swim);bones=rig['bones']
 def frame(u,label,rot=None,offset=None,expr=None,view=0,relax=0,facing=50,front_rot=None):
  p=dict(base);p.update(rot or {});t=copy.deepcopy(base.offsets)
  for k,v in (offset or {}).items():t[k]=v
  return {'phase':u,'label':label,'rotations':p,'translations':t,'expressions':expr or {},'front_mix':view,'relaxed_mix':relax,'facing_angle':facing,'front_rotations':front_rot or {}}
 def arms(targetn,targetf):
  out={}
  for side,target,sign in [('near',targetn,1),('far',targetf,-1)]:
   a,c=ik(rig,'upper_arm_'+side,'forearm_hand_'+side,bones['hand_'+side]['pivot'],target,sign);out['upper_arm_'+side]=a;out['forearm_hand_'+side]=c
  return out
 def save(name,n,fps,loop,keys,samples=None,events=None,transition=None):
  anim={'name':name,'revision':4,'fps':fps,'frame_count':n,'loop':loop,'duration_seconds':n/fps,'sample_phases':samples or [i/n for i in range(n)],'keyframes':keys,'interpolation':'C1 periodic Hermite' if loop else 'clamped eased joint curves; discrete replaceable expression states','secondary':{'mode':'baked cloth follow in shared curves'},'skin_invariant':True,'events':events or {},'event_index_base':1,'transition':transition,'notes':rig['round3_contract']}
  (RIG/f'animations/{name}.json').write_text(json.dumps(anim,ensure_ascii=False,indent=2)+'\n')
 save('gulp',3,12,False,[frame(0,'open mouth / take bubble',expr={'mouth':'gulp_open'}),frame(.5,'swallow / cheeks peak',{'head':-2},expr={'mouth':'cheeks_puffed_mouth'}),frame(1,'cheeks settle / neutral')],[0,.5,1],{'swallow':2})
 hit=[]
 for i,u in enumerate([0,1/3,2/3,1]):
  amount=[.22,1,.42,0][i];rot={k:base[k] for k in bones}
  rot.update(arms([118-18*amount,13+48*amount],[138+12*amount,13+43*amount]))
  rot.update({'head':base['head']+11*amount,'neck':base['neck']+3*amount,'shoulder_near':-5*amount,'shoulder_far':4*amount,'pelvis':-4*amount,'foot_near':base['foot_near']+12*amount,'foot_far':base['foot_far']-8*amount})
  expr={} if i==3 else {'eyes':'cross_eye','mouth':'gasp_mouth','mouth_bubbles':f'bubbles_small_{[1,3,2][i]}'}
  hit.append(frame(u,'localized impact / recover to swim0',rot,expr=expr))
 # The final exported frame is precisely the neutral swim phase0, including cloth.
 hit[-1]=frame(1,'exact swim0 recovery / bubbles cleared')
 save('hit',4,12,False,hit,[0,1/3,2/3,1],transition={'to':{'animation':'swim','phase':0},'last_exported_frame_matches':True,'from_note':'Impact is a deliberate local recoil; arbitrary swim phase still requires runtime blend.'})
 low=[]
 for i,p in enumerate([0,.25,.5,.75]):
  other=r.pose_at(p,rig,swim);rot={k:base[k]+.34*(other[k]-base[k]) for k in bones};rot['head']=base['head']+[-1,2,0,-2][i]
  offset={k:[base.offsets[k][j]+.34*(other.offsets[k][j]-base.offsets[k][j]) for j in range(2)] for k in bones}
  low.append(frame(p,'short urgent pull / breath held',rot,offset,{'eyes':'strained_eye','mouth':'cheeks_puffed_mouth'}))
 save('lowair',4,16,True,low)
 out=[]
 for i,u in enumerate([0,.2,.4,.6,.8,1]):
  views=[0,0,.35,.65,.9,1];relax=[0,0,.32,.65,.9,1]
  rot=arms([118-15*(i/5),13+70*(i/5)],[138+15*(i/5),13+70*(i/5)])
  rot.update({'head':base['head']+4*i,'neck':base['neck']-1.2*i,'pelvis':.7*i,'foot_near':base['foot_near']+2*i,'foot_far':base['foot_far']-2*i})
  expr={'eyes':'closed_eye'}
  if i<2:expr.update({'mouth':'gasp_mouth','mouth_bubbles':f'bubbles_small_{i+1}'})
  fr={'head':-2*i,'neck':-.4*i,'upper_arm_near':1.5*i,'upper_arm_far':-1.5*i,'hand_near':2*i,'hand_far':-2*i,'thigh_near':-1.2*i,'thigh_far':1.2*i,'shin_foot_near':1.8*i,'shin_foot_far':-1.8*i,'foot_near':2*i,'foot_far':-2*i}
  out.append(frame(u,'last exhale / eyes close / chest turns up / limbs release',rot,expr=expr,view=views[i],relax=relax[i],front_rot=fr))
 save('out',6,12,False,out,[0,.2,.4,.6,.8,1])
 turn=[frame(0,'standard swim0 / begin direction change'),frame(.5,'half yaw / shoulders equalize',view=.5,facing=70),frame(1,'front / symmetric body and joints',view=1,facing=90)]
 save('turn',3,24,False,turn,[0,.5,1],transition={'from':{'animation':'swim','phase':0},'last_frame':'frontal symmetric pose; readable NABO wordmark exception for RGB only','mirror_completion':'T0,T1,T2,mirror(T1),mirror(T0); front frame shown once'})
 print('Authored round3: dark outline, legacy timelines unchanged, five new clips, fixed old scale.')
if __name__=='__main__':author()
