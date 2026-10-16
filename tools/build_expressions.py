#!/usr/bin/env python3
"""Build original interchangeable 3/4 face assets without altering neutral art.

All components share the established absolute 256-pixel bind coordinates.
Eyes retain the existing round glasses, bridge, temples and nose marks exactly.
Only files carrying our generator marker may be regenerated in place.
"""
from pathlib import Path
import argparse, copy, hashlib, io, json, re
import xml.etree.ElementTree as ET

BASE=Path(__file__).resolve().parents[1]
OUT=BASE/'rig/common/expressions'
QA=BASE/'preview/qa/expressions'
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
MARK='NABO expressions generator v1'
INK='#1D2938'; SKIN='#F5C394'; SHADE='#DFA072'; DEEP='#B96F50'
WHITE='#F4F7F2'; BLUE='#175383'; LENS='#BDE6E8'

def node(tag,**a):
 return ET.Element('{'+NS+'}'+tag,{k.replace('_','-'):str(v) for k,v in a.items()})
def ellipse(x,y,rx,ry,fill=SKIN,stroke='none',width=0):
 return node('ellipse',cx=x,cy=y,rx=rx,ry=ry,fill=fill,stroke=stroke,stroke_width=width)
def path(d,fill='none',stroke=INK,width=2.6):
 return node('path',d=d,fill=fill,stroke=stroke,stroke_width=width,stroke_linejoin='round',stroke_linecap='round')

def eyes(kind):
 # Neutral indices 4,9,10,11,12 contain the unmodified frame/bridge/temple/nose geometry.
 neutral=list(ET.parse(BASE/'rig/common/eyes_neutral.svg').getroot())[1]
 original=list(neutral)
 shapes=[copy.deepcopy(original[0]),copy.deepcopy(original[5])]
 if kind=='strained':
  shapes += [path('M97 76L111 82L98 88',width=3.4),path('M147 71L137 77L147 82',width=3.2),path('M95 69L109 72M138 67L148 64',width=2.7)]
 elif kind=='closed':
  shapes += [path('M96 82Q105 89 115 81',width=3.3),path('M136 77Q142 83 148 76',width=3.1)]
 elif kind=='cross':
  shapes += [path('M98 76L113 87M112 75L99 88',width=3.5),path('M138 72L146 81M146 72L138 81',width=3.1)]
 elif kind=='surprised':
  shapes += [ellipse(105,81,10.2,10.5,WHITE),ellipse(142,77,6.4,9.5,WHITE),ellipse(105,82,4.3,6,BLUE),ellipse(142,78,3,5.6,BLUE),ellipse(105,83,2.5,4,INK),ellipse(142,79,2,3.7,INK),ellipse(103.8,78.5,1.4,1.7,WHITE),ellipse(141,74.8,1,1.4,WHITE)]
 elif kind=='happy':
  shapes += [path('M96 84Q105 72 115 82',width=3.5),path('M136 79Q142 69 148 77',width=3.1)]
 else:raise ValueError(kind)
 shapes += [copy.deepcopy(original[i]) for i in (4,9,10,11,12)]
 return shapes

def mouths(kind):
 if kind=='gulp_open':
  return [path('M114 96Q122 90 132 95Q135 102 128 107Q117 109 113 102Z',INK,INK,2.6),path('M118 104Q123 99 129 104L126 107L121 107Z',DEEP,'none',0)]
 if kind=='cheeks_puffed_mouth':
  return [path('M102 96Q92 92 89 99Q88 105 98 108Q104 109 109 104',SKIN,INK,2.6),path('M139 94Q147 90 152 96Q154 102 145 105Q140 107 136 103',SKIN,INK,2.6),path('M94 104Q99 107 104 104',stroke=SHADE,width=2.3),path('M141 102Q146 103 150 99',stroke=SHADE,width=2.1),path('M116 99Q122 96 127 98Q124 100 126 102Q121 104 117 102',stroke=INK,width=3)]
 if kind=='gasp_mouth':
  return [ellipse(123,99,6.2,8,INK,INK,2.2),path('M119 103Q123 100 127 103L126 106Q122 108 119 105Z',DEEP,'none',0)]
 if kind=='happy_mouth':
  return [path('M111 96Q122 102 135 94Q131 109 122 108Q114 106 111 96Z',INK,INK,2.4),path('M115 98Q125 101 131 96L129 100Q121 103 116 101Z',WHITE,'none',0),path('M118 105Q124 101 129 104Q126 108 122 107Z',DEEP,'none',0)]
 raise ValueError(kind)

def bubbles(stage):
 # Confined to a short mouth-side emission (under 35 bind px), never a body trail.
 arrangements={1:[(109,109,3.3)],2:[(104,111,4.8),(94,115,3)],3:[(97,112,4),(86,116,2.8),(108,114,2.3)]}
 result=[]
 for x,y,r in arrangements[stage]:
  result += [ellipse(x,y,r,r,LENS,INK,1.5),path(f'M{x-r*.45:.2f} {y-r*.18:.2f}Q{x-r*.35:.2f} {y-r*.65:.2f} {x+r*.05:.2f} {y-r*.58:.2f}',stroke=WHITE,width=max(1.,r*.24))]
 return result

def svg_bytes(name,shapes,slot):
 root=node('svg',width=256,height=256,viewBox='0 0 256 256',data_generator=MARK,data_slot=slot)
 title=ET.SubElement(root,'{'+NS+'}title');title.text=f'Original NABO interchangeable expression: {name}'
 g=ET.SubElement(root,'{'+NS+'}g',{'id':name.replace('_','-')})
 for e in shapes:g.append(e)
 return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def safe_write(file,data):
 if file.exists() and MARK.encode() not in file.read_bytes():
  raise RuntimeError(f'Refusing to overwrite an unowned/different existing file: {file}')
 file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)

def make_assets():
 rig=json.loads((BASE/'rig/rig.json').read_text())
 common=set.intersection(*(set(s['palette'].values()) for s in rig['skins'].values()))
 assets={}
 for kind in ('strained','closed','cross','surprised','happy'):assets[kind+'_eye']=('eyes',eyes(kind))
 for kind in ('gulp_open','cheeks_puffed_mouth','gasp_mouth','happy_mouth'):assets[kind]=('mouth',mouths(kind))
 for stage in (1,2,3):assets[f'bubbles_small_{stage}']=('mouth_bubbles',bubbles(stage))
 index={'generator':MARK,'canvas':[256,256],'coordinate_system':'absolute bind coordinates, no baked root transform','skin_scope':['a','b','c'],'slots':{'eyes':{'bone':'eyes','pivot':[128,80],'parent':'head','replaces':'common/eyes_neutral.svg'},'mouth':{'bone':'mouth','pivot':[124,99],'parent':'head','replaces':'common/mouth_neutral.svg'},'mouth_bubbles':{'suggested_bone':'mouth_bubbles','pivot':[124,99],'parent':'head','draw_after':'mouth','default':None}},'preserved':'All eye assets retain exact original frame, bridge, temple and nose paths. No head or neutral SVG is modified.','assets':{}}
 for name,(slot,shapes) in assets.items():
  data=svg_bytes(name,shapes,slot)
  colors=set(re.findall(r'#[0-9A-Fa-f]{6}',data.decode()))
  if not colors<=common:raise ValueError(f'{name}: non-common palette colors {colors-common}')
  file=OUT/(name+'.svg');safe_write(file,data)
  index['assets'][name]={'slot':slot,'path':str(file.relative_to(BASE/'rig')),'sha256':hashlib.sha256(data).hexdigest(),'rgb':sorted(colors)}
 index['mouth_bubble_policy']='Small localized exhalations for explicitly specified hit and out actions only. No continuous swim/dash trail.'
 file=OUT/'index.json';data=(json.dumps(index,ensure_ascii=False,indent=2)+'\n').encode()
 if file.exists() and json.loads(file.read_text()).get('generator')!=MARK:raise RuntimeError('Unknown expression index exists')
 file.write_bytes(data)
 return assets,index

def qa(assets,index):
 import cairosvg
 from PIL import Image, ImageDraw, ImageFont
 head=list(ET.parse(BASE/'rig/common/head.svg').getroot())[1:]
 neutral_eye=list(ET.parse(BASE/'rig/common/eyes_neutral.svg').getroot())[1:]
 neutral_mouth=list(ET.parse(BASE/'rig/common/mouth_neutral.svg').getroot())[1:]
 QA.mkdir(parents=True,exist_ok=True)
 font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',15)
 rows=[('neutral',None,None,None),('gulp_open',None,'gulp_open',None),('puffed','strained_eye','cheeks_puffed_mouth',None),('hit','cross_eye','gasp_mouth','bubbles_small_2'),('out','closed_eye','gasp_mouth','bubbles_small_3'),('surprised','surprised_eye',None,None),('happy','happy_eye','happy_mouth',None)]
 board=Image.new('RGB',(1000,270*len(rows)),'#101E34');draw=ImageDraw.Draw(board)
 for i,(name,eye,mouth,bubble) in enumerate(rows):
  root=node('svg',width=256,height=256,viewBox='0 0 256 256')
  for e in head:root.append(copy.deepcopy(e))
  for slot,chosen,default in [('eyes',eye,neutral_eye),('mouth',mouth,neutral_mouth)]:
   if chosen:
    g=ET.SubElement(root,'{'+NS+'}g')
    for e in assets[chosen][1]:g.append(copy.deepcopy(e))
   else:
    for e in default:root.append(copy.deepcopy(e))
  if bubble:
   g=ET.SubElement(root,'{'+NS+'}g')
   for e in assets[bubble][1]:g.append(copy.deepcopy(e))
  upright=Image.open(io.BytesIO(cairosvg.svg2png(bytestring=ET.tostring(root)))).convert('RGBA')
  board.paste(upright,(0,i*270),upright)
  draw.text((18,i*270+238),name,font=font,fill='#F4F7F2')
  # Fixed scale of the existing 56px full-body rig, not a head-specific resize.
  group=ET.Element('{'+NS+'}g',{'transform':'translate(128 128) rotate(-140) translate(-128 -128)'})
  for e in list(root):group.append(e)
  root[:]=[group]
  angled=Image.open(io.BytesIO(cairosvg.svg2png(bytestring=ET.tostring(root)))).convert('RGBA')
  s=.257792587
  small=angled.transform((96,96),Image.Transform.AFFINE,(1/s,0,128-48/s,0,1/s,128-48/s),Image.Resampling.BICUBIC)
  small.save(QA/(name+'_fixed_scale_head.png'))
  for j,bg in enumerate(('#0B2A4A','#04070D')):
   tile=Image.new('RGBA',(96,96),bg);tile.alpha_composite(small)
   board.paste(tile.convert('RGB'),(300+j*345,i*270+20))
   enlarged=tile.resize((240,240),Image.Resampling.NEAREST)
   board.paste(enlarged.convert('RGB'),(405+j*345,i*270))
  draw.text((300,i*270+238),'Fixed full-body 56px scale / 2.5x nearest head inset',font=font,fill='#F4F7F2')
 board.save(QA/'contact.png')
 report={'generator':MARK,'checks':{'assets':len(assets),'all_rgb_in_three_skin_palette_intersection':True,'new_rgb':[],'unchanged_originals':{str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [BASE/'rig/common/head.svg',BASE/'rig/common/eyes_neutral.svg',BASE/'rig/common/mouth_neutral.svg']},'visual_qa_contact':'preview/qa/expressions/contact.png','qa_limitation':'Static expression contact only; final action and continuous playback review belongs to the integrated render.'}}
 (QA/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--qa',action='store_true');args=parser.parse_args()
 assets,index=make_assets()
 if args.qa:qa(assets,index)
 print(json.dumps({'created_assets':len(assets),'index':str(OUT/'index.json'),'qa':args.qa}))
if __name__=='__main__':main()
