#!/usr/bin/env python3
"""Round-one static concept authoring. No rig, animation, or firmware output."""
from pathlib import Path
import io, json, math, copy, hashlib
import xml.etree.ElementTree as ET
import numpy as np
import cairosvg
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
P={
 'ink':'#1D2938','rim':'#EAF4F1','white':'#F4F7F2','w1':'#CDDDE2','w2':'#8EA9B7',
 'skin':'#F5C394','s1':'#DFA072','s2':'#B96F50',
 'hair':'#795038','h1':'#54392D','h2':'#322C2A',
 'blue':'#2670B5','b1':'#175383','b2':'#113958','lens':'#BDE6E8',
 'navy':'#183B61','n1':'#122C49','n2':'#0C1C32',
 'coral':'#EF7857','c1':'#C84F3E','c2':'#8E3431',
 'mint':'#A8DED0','m1':'#6FB9AC','m2':'#397E7C',
 'paper':'#F1EDE3','muted':'#6A7B86','deep':'#0B2A4A','black':'#04070D',
 'ochre':'#D6AD63','line':'#D9D4C8','panel':'#FFFFFF','label':'#B6C7CD'}
RGB=[tuple(bytes.fromhex(c[1:])) for c in P.values()]
PAL=Image.new('P',(1,1));PAL.putpalette([n for c in (RGB+[RGB[-1]]*(256-len(RGB))) for n in c])
ACTIVE_PAL=PAL
def set_sprite_palette(kind):
 global ACTIVE_PAL
 keys=['ink','rim','white','w1','w2','skin','s1','s2','hair','h1','h2','blue','b1','b2','lens']
 keys+=dict(a=['navy','n1','n2','ochre'],b=['coral','c1','c2','navy','ochre'],c=['mint','m1','m2','navy'])[kind]
 colors=[tuple(bytes.fromhex(P[k][1:])) for k in keys]
 ACTIVE_PAL=Image.new('P',(1,1));ACTIVE_PAL.putpalette([v for c in (colors+[colors[-1]]*(256-len(colors))) for v in c])
 return keys


def path(d, fill, sw=2.8, stroke='ink', **a):
 attrs={'d':d,'fill':P.get(fill,fill),'stroke':P.get(stroke,stroke),'stroke-width':str(sw),'stroke-linejoin':'round','stroke-linecap':'round'}
 attrs.update({k.replace('_','-'):str(v) for k,v in a.items()})
 return '<path '+' '.join(f'{k}="{v}"' for k,v in attrs.items())+'/>'
def ellipse(x,y,rx,ry,fill,sw=2.8,stroke='ink'):
 return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{P.get(fill,fill)}" stroke="{P.get(stroke,stroke)}" stroke-width="{sw}"/>'
def group(name,body,transform=''):
 return f'<g id="{name}" data-part="{name}"'+(f' transform="{transform}"' if transform else '')+'>'+body+'</g>'
def line(d,fill='ink',sw=2.8):return path(d,'none',sw,fill)

def head(front=False):
 # The crown overlaps the hair, the brim overlaps the forehead: a worn cap, not a decal.
 if front:
  face=path('M87 57 Q88 44 127 45 Q165 45 169 65 L168 82 Q165 103 129 110 Q94 106 88 87 Z','skin')
  face+=path('M154 54 Q169 65 165 86 Q161 101 136 108 L127 108 Q149 98 151 87 Z','s1',0,'none')
  face+=path('M160 76 Q167 85 160 94 L149 100 Q159 86 154 80Z','s2',0,'none')
  ears=ellipse(84,80,10,15,'skin')+ellipse(171,80,10,15,'skin')+line('M82 76 Q89 75 86 85','s1',2.5)+line('M174 76 Q167 75 170 85','s1',2.5)
  hairback=path('M80 46 Q75 36 91 32 Q108 19 126 29 Q150 22 167 39 L174 52 L180 64 L173 63 L181 77 L170 74 L176 90 L166 87 L167 103 L154 98 L146 111 L136 105 L128 112 L116 105 L104 111 L98 98 L85 103 L86 88 L76 91 L80 77 L72 78 L80 64 L72 64 Z','hair')
  fringe=path('M83 53 Q101 41 125 43 Q145 38 169 52 L173 67 Q161 62 153 54 Q158 64 163 69 Q146 69 136 52 Q137 69 146 74 Q126 72 120 53 Q114 67 111 70 Q100 70 97 63 L84 70 L88 60 L78 65Z','hair')
  fringe+=path('M118 46 Q113 63 102 66 L111 70 Q121 65 124 51 L134 63 L129 47Z','h1',0,'none')
  fringe+=path('M84 55L86 65L96 61L97 54Z M157 52L166 64L173 66L169 54Z','h2',0,'none')
  cap=path('M77 48 Q80 19 108 13 Q128 6 150 16 Q174 24 178 49 L167 58 L92 57Z','white')
  cap+=path('M148 17Q173 25 177 49L166 55L159 45Q158 27 148 17Z','w1',0,'none')+path('M167 43L178 49L167 58L157 53Z','w2',0,'none')
  cap+=line('M126 13Q124 27 125 40','w1',1.7)
  cap+=path('M79 46 Q127 31 177 47 L180 54 Q156 52 129 47 Q104 49 79 56 L75 53Z','white')
  cap+=path('M80 54Q104 46 130 46Q156 49 178 53L166 56Q141 52 130 50Q104 51 83 58Z','w1',0,'none')
  eyes=[(108,80,17,14),(149,80,17,14)]
  nose=line('M128 83L126 89L131 90','s1',2.3)
  mouth=line('M118 98Q129 103 140 97','ink',2.1)
  mark='<g transform="translate(0 0)">'+line('M109 27L116 27L120 22L125 31L131 20L136 27L147 27','blue',2.1)+f'<text x="128" y="41" text-anchor="middle" font-family="Arial,sans-serif" font-weight="900" font-size="11.5" fill="{P["blue"]}">NABO</text></g>'
 else:
  face=path('M87 60 Q93 44 123 45 Q151 42 158 61 L159 80 Q157 100 132 110 Q106 114 87 91 L81 76Z','skin')
  face+=path('M145 47Q159 56 159 79Q157 99 133 110L121 110Q143 100 146 82Z','s1',0,'none')
  face+=path('M153 75Q160 88 151 98L138 106Q150 92 148 84Z','s2',0,'none')
  ears=ellipse(84,82,8,12,'skin')+ellipse(164,76,10,15,'skin')+line('M166 72Q159 70 162 82','s1',2.5)
  hairback=path('M81 47 Q78 35 97 28 Q117 17 139 28 Q158 24 169 42 L177 54 L184 63 L175 63 L183 77 L173 75 L178 90 L166 86 L166 101 L154 97 L146 110 L135 105 L124 113 L113 105 L100 109 L96 98 L85 103 L85 90 L76 92 L81 79 L72 79 L79 65 L72 65Z','hair')
  fringe=path('M83 54Q97 43 119 43Q144 36 169 50L174 64Q156 60 149 51Q155 64 162 68Q146 71 132 53Q134 68 144 74Q126 76 115 55Q112 69 103 73L95 65L83 73L87 62L77 67Z','hair')
  fringe+=path('M115 47Q113 61 102 70L107 72Q119 66 120 54Q125 70 139 73L143 73Q128 61 128 45Z','h1',0,'none')
  fringe+=path('M158 50L164 61L174 64L170 52Z M84 57L83 67L94 62L98 52Z','h2',0,'none')
  cap=path('M77 49Q78 23 105 15Q123 7 144 13Q169 20 177 45L173 54L91 58Z','white')
  cap+=path('M144 13Q167 20 177 45L173 54L160 48Q162 28 144 13Z','w1',0,'none')+path('M169 38L177 45L173 54L160 51L164 44Z','w2',0,'none')
  cap+=line('M119 12Q115 24 117 40','w1',1.7)
  cap+=path('M79 47Q116 31 159 42L178 49L180 55Q157 53 137 48Q109 46 80 58L74 55Z','white')
  cap+=path('M78 55Q109 45 137 47L178 54L167 58L138 52Q110 49 82 60Z','w1',0,'none')
  eyes=[(106,81,18,14.5),(143,77,11.2,12)]
  nose=line('M128 82L119 90L127 92','s1',2.2)
  mouth=line('M111 99Q123 104 134 96','ink',2.2)
  mark='<g transform="rotate(-4 122 30)">'+line('M102 28L109 28L114 23L119 31L125 20L131 27L141 27','blue',2.1)+f'<text x="122" y="41" text-anchor="middle" font-family="Arial,sans-serif" font-weight="900" font-size="11.5" fill="{P["blue"]}">NABO</text></g>'
 features=''
 for i,(x,y,rx,ry) in enumerate(eyes):
  # Open lenses leave skin visible; one clean ring, generous eye shapes at native size.
  features+=ellipse(x,y+1,rx-2,ry-2,'skin',0,'none')
  features+=ellipse(x-1,y,6.6 if i==0 or front else 4.7,8,'b1',0,'none')
  features+=ellipse(x-1,y+2,4,5,'ink',0,'none')
  features+=ellipse(x-3,y-3,2.2,2.7,'white',0,'none')
  features+=ellipse(x,y,rx,ry,'none',2.5,'ink')
 features+=line('M124 78Q128 74 132 77','ink',2.4) if not front else line('M125 78Q129 75 132 78','ink',2.4)
 features+=line('M88 77L81 72M154 72L165 65','ink',2.4) if not front else line('M91 76L82 70M166 76L174 70','ink',2.4)
 features+=nose+mouth
 return group('head',group('hair-back',hairback)+group('ears',ears)+group('face',face)+group('hair-fringe',fringe)+group('face-expression',features)+group('cap',cap+mark))


def body(kind,front=False):
 suit={'a':'navy','b':'coral','c':'mint'}[kind]
 sh1={'a':'n1','b':'c1','c':'m1'}[kind];sh2={'a':'n2','b':'c2','c':'m2'}[kind]
 parts=[]
 def add(name,b):parts.append(group(name,b))
 # Silhouette of sleeves / hands is intentionally broad rather than finger detail.
 if front:
  far_arm=path('M149 115Q159 114 164 128L170 153L158 157L148 134Z','white' if kind!='c' else 'mint')
  far_arm+=path('M163 132L170 153L165 155L157 134Z','w1' if kind!='c' else 'm1',0,'none')
  far_arm+=path('M159 151L170 149L174 164Q174 172 168 173Q160 174 159 165Z','skin')
  near_arm=path('M106 115Q98 114 92 128L85 153L97 158L110 133Z','white' if kind!='c' else 'mint')
  near_arm+=path('M91 133L85 153L90 156L99 135Z','w1' if kind!='c' else 'm1',0,'none')
  near_arm+=path('M86 150L97 152L97 165Q96 173 89 173Q81 172 83 164Z','skin')
  legs=[('left','M108 162L128 163L125 195L119 218L105 216L109 192Z','M107 208L122 211L122 224Q113 232 98 227L98 220Z'),('right','M128 163L148 162L147 192L151 217L136 219L130 194Z','M135 211L150 208L159 220L159 227Q145 233 135 224Z')]
 else:
  far_arm=path('M148 116Q156 116 161 127L171 136L165 149Q152 145 145 135Z','white' if kind!='c' else 'mint')
  far_arm+=path('M170 136L184 120L192 127L175 149Q171 154 165 149Z','white' if kind!='c' else 'mint')
  far_arm+=path('M182 123L180 116Q179 107 186 107Q193 107 194 116L193 127Z','skin')
  far_arm+=path('M156 126L168 141L174 136L169 146L165 148L154 137Z','w1' if kind!='c' else 'm1',0,'none')
  near_arm=path('M107 115Q99 113 91 119L79 129L86 141L102 134L112 126Z','white' if kind!='c' else 'mint')
  near_arm+=path('M79 128L74 111L85 105L91 127L86 140Z','white' if kind!='c' else 'mint')
  near_arm+=path('M74 114L70 106Q68 98 75 95Q83 93 86 101L86 108Z','skin')
  near_arm+=path('M78 114L84 112L90 129L85 136Z','w1' if kind!='c' else 'm1',0,'none')
  legs=[('left','M109 160L128 165L116 188L118 208L103 212L99 187Z','M102 202L118 202L122 218Q116 225 100 222L97 216Z'),('right','M129 164L147 159L164 181L159 204L144 203L148 184Z','M145 198L160 200L168 214Q162 223 148 221L142 214Z')]
 add('arm-far',far_arm)
 for side,leg,shoe in legs:
  legcol=suit if kind!='a' else 'navy'
  b=path(leg,legcol)+path('M111 171L118 175L111 189L113 204L106 205L104 187Z' if side=='left' else 'M140 171L148 168L158 182L153 201L147 200L151 184Z',sh1,0,'none')
  if front:
   b=path(leg,legcol)+path('M111 172L117 175L113 199L111 211L106 211L110 193Z' if side=='left' else 'M141 170L147 168L146 191L150 213L144 215L138 190Z',sh1,0,'none')
  if kind=='c':
   b+=path('M103 199L117 198L119 207L103 212Z' if side=='left' else 'M145 196L160 198L159 206L144 204Z','navy',0,'none') if not front else path('M106 205L121 207L119 217L105 215Z' if side=='left' else 'M135 208L150 205L151 216L136 218Z','navy',0,'none')
  add(f'leg-{side}',b)
  b=path(shoe,'white')
  if front:b+=path('M99 223Q112 228 121 221L121 225Q111 231 99 227Z' if side=='left' else 'M136 221Q148 229 158 223L158 227Q147 232 136 225Z','w2',0,'none')
  else:b+=path('M99 216Q110 223 121 215L120 220Q110 226 100 222Z' if side=='left' else 'M144 214Q155 221 166 213L168 216Q160 224 149 221Z','w2',0,'none')
  add(f'shoe-{side}',b)
 if kind=='a':
  add('floating-coat-tail',path('M142 151Q157 164 163 185L148 184L134 166Z','white')+path('M145 160L158 182L148 179L139 165Z','w1',0,'none'))
  add('short-coat-tail',path('M108 151L124 162L111 181L96 178Z','white')+path('M108 163L113 168L105 177L98 176Z','w1',0,'none'))
 if kind=='b':
  add('floating-rescue-ribbon',path('M146 150Q164 149 173 163Q181 174 194 164L195 175Q180 186 166 173Q155 159 147 161Z','white')+path('M151 155Q165 155 172 169Q180 179 194 170L194 175Q181 185 166 173L151 162Z','w1',0,'none'))
 if kind=='c':
  add('floating-collar-tab',path('M145 114Q166 119 171 137Q174 152 190 153L188 164Q169 164 162 149L145 127Z','blue')+path('M158 124Q170 137 172 149Q178 157 189 157L188 164Q169 164 162 149L151 132Z','b1',0,'none'))
 add('neck',path('M117 102L138 102L139 121L118 122Z','skin')+path('M120 105L138 105L138 116L121 114Z','s1',0,'none'))
 torso=path('M112 111Q127 116 145 111L151 125L149 164Q128 177 106 163L105 127Z',suit)
 torso+=path('M140 114L150 124L148 163L132 168L135 153Z',sh1,0,'none')
 torso+=path('M142 141L149 135L148 163L136 168L139 155Z',sh2,0,'none')
 if kind=='a':
  torso+=path('M113 112L126 124L117 136L109 128Z','white')+path('M143 112L128 124L138 136L148 128Z','white')
  torso+=path('M108 120L119 130L117 149L121 168L106 166L103 155L104 129Z','white')+path('M145 121L136 130L139 149L134 170L150 165L151 133Z','white')
  torso+=path('M108 141L113 145L113 161L119 167L107 164L104 155Z','w1',0,'none')+path('M144 143L150 139L149 164L136 169L141 156Z','w1',0,'none')
  torso+=path('M111 146L122 146L122 153L111 153Z','w1',1.5)
  torso+=line('M116 118Q108 122 112 136Q115 145 124 140M140 119L139 142L132 150','ink',3.3)+ellipse(131,151,5.3,5.3,'ochre',2,'ink')
 elif kind=='b':
  torso+=path('M111 113L117 117L112 142L105 141L106 126Z','white')+path('M142 113L147 118L150 140L142 142L137 118Z','white')
  torso+=path('M106 153L149 153L149 162Q129 169 106 162Z','navy')+path('M122 154L133 154L133 164L122 164Z','ochre',2)
  torso+=line('M126 125L125 148','c2',2.2)
  torso+=path('M119 136L125 130L131 136L125 142Z','white',0,'none')
 else:
  torso+=path('M112 113L120 118L128 130L136 118L144 114L145 122L128 141L109 122Z','white')
  torso+=path('M105 136L113 140L119 161L109 165L105 157Z','navy',0,'none')
  torso+=path('M144 136L150 133L149 158L140 165L138 158Z','navy',0,'none')
  torso+=path('M123 149L129 145L135 149L129 153Z','blue',0,'none')
 add('torso',torso)
 add('arm-near',near_arm)
 return ''.join(parts)


def make_svg(kind,front=False):
 base=body(kind,front)+head(front)
 pose='' if front else 'rotate(-140 128 128)'
 # Underlay every filled component in pale color, then draw the complete colored assembly.
 # This produces one hard outer rim around the union, with no glow or gradient.
 root=ET.fromstring('<g>'+base+'</g>')
 for e in root.iter():
  if e.tag in ('path','ellipse','circle','rect','polygon'):
   e.set('fill',P['rim'] if e.get('fill')!='none' else 'none');e.set('stroke',P['rim']);e.set('stroke-width','12');e.set('stroke-linejoin','round');e.set('stroke-linecap','round')
  if e.tag=='text':e.set('fill',P['rim']);e.set('stroke',P['rim']);e.set('stroke-width','5')
  if e.get('id'):e.set('id','rim-'+e.get('id'))
 outline=ET.tostring(root,encoding='unicode')
 s=f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><title>NABO DIVE option {kind.upper()} / {"front" if front else "down-left 50 degrees, three-quarter face"}</title><desc>Original static vector concept. Chest anchor (128,128). Flat base and two hard cel-shadow levels; hard pale silhouette. Named groups retained for later part extraction, no animation or rig.</desc><g id="pose" transform="{pose}"><g id="outer-rim">{outline}</g><g id="colored-parts">{base}</g></g></svg>'
 return s


def fixed_rgba(im):
 """At most 32 RGB entries, independent 16-level alpha; alpha-edge RGB stays in palette."""
 im=im.convert('RGBA');a=np.array(im.getchannel('A'),dtype=np.float32)
 rgb=im.convert('RGB').quantize(palette=ACTIVE_PAL,dither=Image.Dither.NONE).convert('RGB')
 rgb.putalpha(Image.fromarray((np.round(a/17)*17).astype('uint8')))
 return rgb

def render(svg,size=256):
 raw=Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(),output_width=size*3,output_height=size*3))).convert('RGBA')
 return fixed_rgba(raw.resize((size,size),Image.Resampling.LANCZOS))

def cropped(im):return im.crop(im.getchannel('A').getbbox())
def actual56(im):
 im=cropped(im);w=round(im.width*56/im.height)
 return fixed_rgba(im.resize((w,56),Image.Resampling.LANCZOS))

EN='/System/Library/Fonts/Supplemental/Arial.ttf'
BOLD='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
CN='/System/Library/Fonts/STHeiti Medium.ttc'
def font(n,bold=False,cn=False):return ImageFont.truetype(CN if cn else (BOLD if bold else EN),n)
def t(draw,xy,s,n=22,c='ink',bold=False,cn=False):draw.text(xy,s,font=font(n,bold,cn),fill=P.get(c,c))
def paste_fit(canvas,im,box):
 im=cropped(im);x,y,w,h=box;k=min(w/im.width,h/im.height);im=im.resize((round(im.width*k),round(im.height*k)),Image.Resampling.LANCZOS)
 canvas.paste(im,(round(x+(w-im.width)/2),round(y+(h-im.height)/2)),im)
def rgb565(h):
 r,g,b=bytes.fromhex(h[1:]);return f'0x{((r>>3)<<11)|((g>>2)<<5)|(b>>3):04X}'

OPTIONS={
 'a':dict(title='白褂潜行',en='THE DOCTOR',accent='blue',col=['navy','n1','n2'],tag='身份保留最多 · 短白大褂 / 深蓝刷手服',notes=['白大褂 + 听诊器：医生身份直接','双片短衣摆：提供水流跟随','配饰最多，56 px 只保留大形'],float='双片短衣摆',complexity='细节较多 / 19 色'),
 'b':dict(title='珊瑚救援',en='RESCUE CORAL',accent='coral',col=['coral','c1','c2'],tag='服装改动最大 · 珊瑚橙救援夹克',notes=['暖橙整块：与深海拉开反差','白色救援织带：独立飘动部件','省略听诊器，腰带与肩带留形'],float='腰侧救援织带',complexity='中等简化 / 20 色'),
 'c':dict(title='薄荷深潜',en='MINT STREAM',accent='m2',col=['mint','m1','m2'],tag='造型最精简 · 薄荷白一体潜水服',notes=['连体服大色块：小尺寸更集中','蓝色宽领带尾：独立飘动部件','无衣襟口袋，轮廓轻而干净'],float='蓝色宽领带尾',complexity='高度简化 / 19 色')}


def board(kind,diver,front,small):
 o=OPTIONS[kind];im=Image.new('RGB',(1600,1200),P['paper']);d=ImageDraw.Draw(im)
 d.rectangle((0,0,1600,13),fill=P[o['accent']]);t(d,(54,38),'NABO  /  DIVE',26,bold=True)
 t(d,(54,84),f'{kind.upper()}   {o["title"]}',48,bold=True,cn=True)
 t(d,(550,102),o['en'],24,o['accent'],True)
 t(d,(54,151),o['tag'],22,'muted',cn=True)
 d.rounded_rectangle((1300,51,1546,113),radius=4,fill=P['ink']);t(d,(1320,65),'ROUND 01 / SELECT',19,'white',True)
 t(d,(1304,131),'STATIC CONCEPT',18,'muted',True)
 d.line((54,190,1546,190),fill=P['line'],width=2)
 # Two views. No invented action sequence, lens effects, or engine-rendered VFX.
 t(d,(58,217),'01',22,o['accent'],True);t(d,(104,215),'标准潜姿 / 3/4 面向观众',23,cn=True)
 t(d,(58,251),'DOWN-LEFT 50°',17,'muted',True)
 t(d,(746,217),'02',22,o['accent'],True);t(d,(791,215),'正面造型',23,cn=True)
 t(d,(746,251),'FRONT / FULL BODY',17,'muted',True)
 paste_fit(im,diver,(45,292,665,467));paste_fit(im,front,(742,286,350,478))
 d.line((1129,215,1129,762),fill=P['line'],width=2)
 t(d,(1165,217),'03   配色 / COLOR',22,cn=True)
 t(d,(1165,255),'BASE  /  SHADOW 1  /  SHADOW 2',13,'muted',True)
 rows=[('白帽与白鞋',['white','w1','w2']),('棕发',['hair','h1','h2']),('肤色',['skin','s1','s2']),('服装',o['col']),('帽标 / 镜框',['blue','ink','rim'])]
 for j,(lab,cols) in enumerate(rows):
  y=286+j*73;t(d,(1165,y),lab,16,'muted',cn=True)
  for k,c in enumerate(cols):
   x=1165+k*122;d.rectangle((x,y+27,x+107,y+51),fill=P[c]);t(d,(x,y+55),P[c],12,'muted')
 t(d,(1165,672),'DESIGN NOTES',17,o['accent'],True)
 for j,s in enumerate(o['notes']):t(d,(1165,704+j*24),s,14,'ink',cn=True)
 # Each panel contains an unscaled 56px-tall character and its exact nearest-neighbor x4.
 for j,bg in enumerate(['deep','black']):
  x=54+j*760;y=804;d.rounded_rectangle((x,y,x+732,1145),radius=8,fill=P[bg])
  t(d,(x+24,y+19),f'04   {P[bg]}',20,'white',True)
  t(d,(x+24,y+52),'角色实际高 56 px',18,'label',cn=True)
  sx=x+49;sy=y+136;im.paste(small,(sx,sy),small)
  t(d,(x+26,y+220),'1× / 56 px',16,'label',True)
  big=small.resize((small.width*4,224),Image.Resampling.NEAREST)
  im.paste(big,(x+242,y+83),big)
  t(d,(x+491,y+22),'NEAREST ×4',16,'label',True)
  t(d,(x+491,y+54),'224 px',16,'label')
 t(d,(54,1163),'白帽 / 棕发 / 圆镜保留     ·     浅色硬描边     ·     原创 SVG     ·     本轮仅供选型',18,'muted',cn=True)
 t(d,(1350,1165),f'OPTION {kind.upper()} / 03',17,'muted',True)
 return im.quantize(palette=PAL,dither=Image.Dither.NONE)


def main():
 report={'stage':'Round 1 static concepts only; await user selection','source':'Original SVG drawings, no image generation or copied pixels','documents':'Existing ART_BRIEF.md and CODEX_PROMPTS.md match Library text apart from final newline; preserved unchanged','palette_rgb_limit':32,'alpha_levels':list(range(0,256,17)),'chest_anchor':[128,128],'body_direction_degrees_from_positive_x':130,'options':{}}
 for kind in OPTIONS:
  views={};palette_keys=set_sprite_palette(kind)
  for view,fr in [('dive',False),('front',True)]:
   svg=make_svg(kind,fr);(ROOT/'sources'/f'option_{kind}_{view}.svg').write_text(svg)
   pic=render(svg);pic.save(ROOT/'sources'/f'option_{kind}_{view}.png');views[view]=pic
  small=actual56(views['dive']);small.save(ROOT/'previews'/f'option_{kind}_56.png')
  small.resize((small.width*4,224),Image.Resampling.NEAREST).save(ROOT/'previews'/f'option_{kind}_56_4x.png')
  for bg in ['deep','black']:
   p=Image.new('RGB',(180,104),P[bg]);p.paste(small,((180-small.width)//2,24),small);p.quantize(palette=PAL,dither=Image.Dither.NONE).save(ROOT/'previews'/f'option_{kind}_{bg}_actual.png')
   # The full composited native preview is enlarged without smoothing, exactly 4 times.
   p.resize((720,416),Image.Resampling.NEAREST).quantize(palette=PAL,dither=Image.Dither.NONE).save(ROOT/'previews'/f'option_{kind}_{bg}_4x.png')
  sheet=board(kind,render(make_svg(kind,False),1024),render(make_svg(kind,True),1024),small);sheet.save(ROOT/f'option_{kind}.png')
  def stats(pic):
   ar=np.array(pic.convert('RGBA'));vis=ar[:,:,3]>0
   return {'canvas':list(pic.size),'visible_bbox':list(pic.getchannel('A').getbbox()),'distinct_rgb_visible':len(np.unique(ar[:,:,:3][vis],axis=0)),'distinct_alpha':sorted(int(x) for x in np.unique(ar[:,:,3]))}
  report['options'][kind]={'sprite_palette_entries':len(palette_keys),'sprite_palette':{k:P[k] for k in palette_keys},'dive':stats(views['dive']),'front':stats(views['front']),'actual':stats(small),'floating_part':OPTIONS[kind]['float'],'sheet_size':list(sheet.size),'sheet_rgb_colors':len(sheet.getcolors(1000000)),'sha256':hashlib.sha256((ROOT/f'option_{kind}.png').read_bytes()).hexdigest()}
 (ROOT/'qa'/'checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 (ROOT/'sources'/'palette.json').write_text(json.dumps({k:{'rgb':v,'rgb565':rgb565(v)} for k,v in P.items()},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
