#!/usr/bin/env python3
"""Read-only artwork QA for the authorized, reduced DIVE round 3.

Only preview/qa/round3-validation.json is written. No old validator or archive is
modified. Source renders, recoloring controls and symmetry masks stay in memory.
"""
from __future__ import annotations
import argparse
import copy
from fractions import Fraction
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

SKINS=('a','b','c')
SPEC={'swim':(8,12,True),'dash_in':(3,12,False),'dash':(4,12,True),'dash_out':(3,12,False),'gulp':(3,12,False),'hit':(4,12,False),'lowair':(4,16,True),'out':(6,12,False),'turn':(3,24,False)}
OLD=('swim','dash_in','dash','dash_out')
NEW=('gulp','hit','lowair','out','turn')
SCALE=0.25779258710765557
RIM='#101E34'
BACKGROUNDS=['#3FA9D6','#1B5E8C','#0B2A4A','#061528','#04070D']
APPROVED_SPECS={'ART_BRIEF.md':'ec6ba21e9c3dcccdb0453158972946b2cd36abcb8ac7bd27a078c3a423ed5cd7','CODEX_PROMPTS.md':'d09722007899fa2bbd67b9f084147fbe06d81365a11d989076475cf4c7b0469b'}
OLD_TIMELINES={'swim':'ea4564fe73ef61cfdd6a8e3f2eb5a0168c5dd44a0ddba320e50deebee221b5be','dash_in':'daf50269cdc059aaff96cab9b13d3f41a68ff6b4bb06982820927617a5976266','dash':'b33b52f4b65c84a550b2b7045fe959b8bc3267287b9ba413282b94254d2a5156','dash_out':'31bee39b4a23611ea273fc8be3c718535d87e281db092b89dc8d3e6b43db0a2b'}
EPS=1e-9


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def exact(a,b):
    return a.mode==b.mode and a.size==b.size and all(hi==0 for lo,hi in ImageChops.difference(a,b).getextrema())

def visible_equal(a,b):
    if a.size!=b.size:return False
    a,b=a.convert('RGBA'),b.convert('RGBA')
    if not exact(a.getchannel('A').convert('RGB'),b.getchannel('A').convert('RGB')):return False
    diff=ImageChops.difference(a.convert('RGB'),b.convert('RGB'))
    return not ImageChops.multiply(diff,Image.merge('RGB',(a.getchannel('A').point(lambda v:255 if v else 0),)*3)).getbbox()

def masked_error(a,b,mask):
    if a.size!=b.size or a.size!=mask.size or not mask.getbbox():return float('inf')
    return sum(ImageStat.Stat(ImageChops.difference(a.convert('RGB'),b.convert('RGB')),mask).mean)/3

def preview_error(a,b,mask):
    if a.size!=b.size or a.size!=mask.size:return 255.0
    bg=ImageOps.invert(mask)
    diff=ImageChops.multiply(ImageChops.difference(a.convert('RGB'),b.convert('RGB')),Image.merge('RGB',(bg,)*3))
    if diff.getbbox():return 255.0
    return masked_error(a,b,mask)

def durations(fps_values):
    elapsed=Fraction(0);previous=0;result=[]
    for fps in fps_values:
        elapsed+=Fraction(1000,fps)
        current=math.floor(elapsed/10+Fraction(1,2))*10
        result.append(current-previous);previous=current
    return result

def nn4(im):
    return im.width%4==0 and im.height%4==0 and exact(im,im.resize((im.width//4,im.height//4),Image.Resampling.NEAREST).resize(im.size,Image.Resampling.NEAREST))

def import_renderer(path,name):
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def raw_pixels(im):return im.get_flattened_data() if hasattr(im,'get_flattened_data') else im.getdata()

def expression_state(ids):
    return {'eyes':ids.get('eyes',ids.get('eye')) or 'neutral','mouth':ids.get('mouth') or 'neutral','mouth_bubbles':ids.get('mouth_bubbles',ids.get('bubbles')) or 'empty'}


class Audit:
    def __init__(self,root):
        self.root=root;self.checks=[];self.observations=[];self.evidence={'gif_pixel_comparison':'Foreground mean RGB error must stay below1 after GIF palette quantization. Every alpha0 background pixel must match the declared background exactly; any mismatch is represented by error255.'}
        self.rig=None;self.anims={};self.images={};self.metas={};self.smalls={};self.gifs={}
        self.archive=root/'history/round2_v3';self.oldrig=None;self.module=None;self.oldmodule=None

    def check(self,name,passed,details=None):
        item={'check':name,'passed':bool(passed)}
        if details is not None:item['details']=details
        self.checks.append(item);return bool(passed)

    def json(self,path):
        path=Path(path)
        if not path.is_absolute():path=self.root/path
        try:return json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:
            self.check(str(path)+': readable JSON',False,str(exc));return None

    def baselines(self):
        now={path:digest(self.root/path) if (self.root/path).is_file() else None for path in APPROVED_SPECS}
        self.check('current user-supplied specifications unchanged',now==APPROVED_SPECS,now)
        base=self.json('preview/qa/round1-baseline-sha256.json')
        design={path:h for path,h in base.items() if path.startswith('design/')} if isinstance(base,dict) else {}
        changed=[path for path,h in design.items() if not (self.root/path).is_file() or digest(self.root/path)!=h]
        self.check('original design41 preserved',len(design)==41 and not changed,{'checked':len(design),'changed':changed})
        for version,count in (('round2_v1',116),('round2_v2',214),('round2_v3',304)):
            data=self.json(f'history/{version}/snapshot.json')
            files=data.get('files',data) if isinstance(data,dict) else {}
            valid=isinstance(files,dict) and len(files)==count and all(isinstance(value,str) and len(value)==64 for value in files.values())
            self.check(f'{version}: immutable snapshot file count',valid,{'expected':count,'found':len(files)})
            if valid:
                home=self.root/'history'/version
                changed=[path for path,h in files.items() if not (home/path).is_file() or digest(home/path)!=h]
                self.check(f'{version}: archive SHA256 unchanged',not changed,{'checked':len(files),'changed':changed})
                if version=='round2_v3':
                    for path in ('tools/validate_swim.py','preview/qa/validation.json'):
                        self.check(f'old {path} left unchanged',path in files and digest(self.root/path)==files[path])
        self.oldrig=self.json(self.archive/'rig/rig.json')
        self.evidence['user_animation_review']='pending; round3 execution approval does not approve earlier motion'
        self.evidence['visual_review']={'method':'Explicit view_image inspection of static PNGs; no browser or continuous GIF playback.','source_contacts':[f'preview/{name}_contact.png' for name in NEW],'source_poses_inspected':60,'actual_scale_contacts':[f'preview/qa/{name}-actual-contact.png' for name in NEW],'actual_scale_background_cells_inspected':120,'additional_contacts':['preview/qa/turn-five-frame-contact.png','preview/qa/hit-seams.png'],'findings':['No obvious canvas clipping, detached limbs, or hat/glasses occlusion in the inspected cells.','Turn five-sample left/front/right sequence and hit entry/recovery seam cells have coherent ordering.','Gulp mouth changes are subtle at the retained actual scale; performance strength and timing still require user review.']}

    def rig_and_sources(self):
        self.rig=self.json('rig/rig.json')
        if not isinstance(self.rig,dict) or not isinstance(self.oldrig,dict):return
        rig=self.rig;old=self.oldrig
        self.check('fixed 256 canvas and chest anchor',rig.get('canvas')==[256,256] and rig.get('anchor')==[128,128])
        original=old['bones'];bones=rig.get('bones',{})
        self.check('original24 bones/pivots/parents preserved',len(original)==24 and all(bones.get(name)==value for name,value in original.items()))
        self.check('only authorized mouth_bubbles child bone added',set(bones)==set(original)|{'mouth_bubbles'} and bones.get('mouth_bubbles',{}).get('parent')=='head' and bones.get('mouth_bubbles',{}).get('pivot')==[124,99])
        self.check('dark outline color, same source geometry width',rig.get('outline',{}).get('rgb','').upper()==RIM and rig['outline'].get('source_stroke_width')==old['outline']['source_stroke_width'],rig.get('outline'))
        for skin in SKINS:
            before=old['skins'][skin]['palette'];after=rig['skins'][skin]['palette']
            expected=dict(before);expected['rim']=RIM
            self.check(f'{skin}: existing palette only changes rim color',list(after)==list(before) and after==expected,{'before':before,'after':after})
        for name,h in OLD_TIMELINES.items():
            self.check(f'{name}: old timeline JSON byte-identical',digest(self.root/f'rig/animations/{name}.json')==h and digest(self.archive/f'rig/animations/{name}.json')==h)
        self.check('exactly nine authorized action timelines',sorted(p.name for p in (self.root/'rig/animations').glob('*.json') if not p.name.startswith('._'))==sorted(name+'.json' for name in SPEC))
        bad=[];count=0
        for path in (self.root/'rig').rglob('*.svg'):
            if path.name.startswith('._'):continue
            count+=1
            try:
                svg=ET.parse(path).getroot()
                forbidden=[element.tag.rsplit('}',1)[-1] for element in svg.iter() if element.tag.rsplit('}',1)[-1] in ('image','filter','linearGradient','radialGradient')]
                if forbidden:bad.append({'file':str(path.relative_to(self.root)),'forbidden':forbidden})
            except (OSError,ET.ParseError) as exc:bad.append({'file':str(path),'error':str(exc)})
        self.check('vector components parse without raster/gradient/glow',count>0 and not bad,{'svg_count':count,'failures':bad})
        self.catalog=self.json('rig/common/expressions/index.json')
        if isinstance(self.catalog,dict):
            failed=[]
            for name,item in self.catalog.get('assets',{}).items():
                path=self.root/'rig'/item['path']
                if not path.is_file() or digest(path)!=item.get('sha256'):failed.append(name)
            self.check('expression catalog SVG hashes resolve',bool(self.catalog.get('assets')) and not failed,failed)
            self.check('rig expression IDs map exactly to hash-checked catalog',rig.get('expressions')==self.catalog.get('assets'))
        for name,(count,fps,loop) in SPEC.items():
            anim=self.json(f'rig/animations/{name}.json')
            if not isinstance(anim,dict):continue
            self.anims[name]=anim
            self.check(f'{name}: exact count/fps/loop',anim.get('frame_count')==count and anim.get('fps')==fps and anim.get('loop') is loop)
            samples=anim.get('sample_phases',[])
            self.check(f'{name}: explicit finite export phases',len(samples)==count and all(isinstance(p,(float,int)) and 0<=p<=1 for p in samples) and samples==sorted(set(samples)),samples)
            if name=='hit':self.check('hit includes terminal phase1 sample',bool(samples) and samples[-1]==1)
            if name=='turn':self.check('turn includes symmetric terminal phase1 sample',bool(samples) and samples[-1]==1)
            if name=='lowair':self.check('lowair periodic samples exclude duplicate terminal',samples==[0,.25,.5,.75])
            keys=anim.get('keyframes',[])
            self.check(f'{name}: tracks cover original skeleton',bool(keys) and all(set(original)<=set(k.get('rotations',{})) and set(original)<=set(k.get('translations',{})) for k in keys))

    def gif(self,path,count,fps_values,loop,size):
        try:
            im=Image.open(self.root/path);frames=[];times=[];setting=im.info.get('loop')
            for i in range(im.n_frames):
                im.seek(i);frames.append(im.convert('RGB').copy());times.append(im.info.get('duration'))
            expected=durations(fps_values)
            self.check(f'{path}: decoded count/timing/loop',len(frames)==count and times==expected and setting==(0 if loop else None),{'count':len(frames),'duration_ms':times,'expected_ms':expected,'loop':setting,'total_ms':sum(times)})
            self.check(f'{path}: expected preview geometry',im.size==size,list(im.size))
            self.gifs[path]=frames
            return frames
        except (OSError,EOFError) as exc:
            self.check(f'{path}: readable GIF',False,str(exc));return []

    def quantized_small(self,source,skin):
        result=source.transform((96,96),Image.Transform.AFFINE,(1/SCALE,0,128-48/SCALE,0,1/SCALE,128-48/SCALE),Image.Resampling.BICUBIC)
        colors=[tuple(int(color[i:i+2],16) for i in (1,3,5)) for color in self.rig['skins'][skin]['palette'].values()]
        palette=Image.new('P',(1,1));palette.putpalette([v for c in colors+[colors[-1]]*(256-len(colors)) for v in c])
        rgb=result.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE).convert('RGB')
        rgb.putalpha(result.getchannel('A').point(lambda value:round(value/17)*17));return rgb

    def frame_group(self,skin,name):
        count,fps,loop=SPEC[name];key=(skin,name);label=f'{skin}/{name}'
        folder=self.root/f'frames/{skin}/{name}'
        names=[f'{i+1:02d}.png' for i in range(count)]
        self.check(label+': exact frame files',sorted(path.name for path in folder.glob('*.png') if not path.name.startswith('._'))==names)
        frames=[];palette=set();alpha=set();boxes=[];hashes=[]
        for file in names:
            raw=Image.open(folder/file)
            self.check(label+'/'+file+': 256 RGBA PNG',raw.size==(256,256) and raw.mode=='RGBA' and raw.format=='PNG')
            im=raw.convert('RGBA');frames.append(im);hashes.append(hashlib.sha256(im.tobytes()).hexdigest())
            pixels=list(raw_pixels(im));palette.update(pixel[:3] for pixel in pixels if pixel[3]>0);alpha.update(pixel[3] for pixel in pixels)
            bbox=im.getchannel('A').getbbox();boxes.append(list(bbox) if bbox else None)
        self.images[key]=frames
        self.check(label+': frames distinct',len(set(hashes))==count)
        self.check(label+': <=32 visible RGB colors over cycle',len(palette)<=32,{'colors':len(palette),'palette':['#%02X%02X%02X'%c for c in sorted(palette)]})
        self.check(label+': alpha on 16-level grid',alpha<=set(range(0,256,17)),sorted(alpha))
        self.check(label+': no empty or clipped alpha',all(b and min(b[:2])>0 and max(b[2:])<256 for b in boxes),boxes)
        meta=self.json(f'frames/{skin}/{name}/metadata.json');self.metas[key]=meta
        if not isinstance(meta,dict):return
        rows=meta.get('frames',[]);preview=meta.get('preview',{})
        self.check(label+': metadata timing/loop and chest',meta.get('canvas')==[256,256] and meta.get('anchor')==[128,128] and meta.get('fps')==fps and meta.get('frame_count')==count and meta.get('loop') is loop)
        anchors=[row.get('anchor_world',[]) for row in rows]
        error=max((abs(value-128) for point in anchors for value in point),default=float('inf'))
        self.check(label+': every sampled chest anchor fixed',len(anchors)==count and all(len(point)==2 for point in anchors) and error<EPS,{'maximum_error_px':error})
        self.check(label+': metadata phase/bounds match source',len(rows)==count and [row.get('phase') for row in rows]==self.anims[name]['sample_phases'] and [row.get('visible_bbox') for row in rows]==boxes)
        self.check(label+': current timeline provenance',meta.get('timeline_sha256')==digest(self.root/f'rig/animations/{name}.json'))
        skeleton_hash=hashlib.sha256(json.dumps(self.rig['bones'],sort_keys=True).encode()).hexdigest()
        self.check(label+': same shared skeleton provenance',meta.get('shared_skeleton_sha256')==skeleton_hash)
        if name in NEW:
            projection=[row.get('view_projection',{}) for row in rows]
            self.check(label+': action projection metadata explicit',all(all(isinstance(row.get(field),(float,int)) for field in ('front_mix','relaxed_mix','facing_angle')) for row in projection),projection)
            expression=[row.get('expressions') for row in rows]
            valid_expressions=len(expression)==count and all(isinstance(row,dict) and set(row)<={'eyes','mouth','mouth_bubbles'} and all(value in self.rig['expressions'] and self.rig['expressions'][value]['slot']==slot for slot,value in row.items()) for row in expression)
            self.check(label+': explicit expression IDs resolve; omitted slots use neutral/empty defaults',valid_expressions,[expression_state(row) for row in expression] if all(isinstance(row,dict) for row in expression) else expression)
        self.check(label+': original actual scale retained',preview.get('scale_to_actual')==SCALE and preview.get('actual_anchor')==[48,48] and preview.get('actual_frame_canvas')==[96,96],preview.get('scale_to_actual'))
        directory=preview.get('actual_frames_dir')
        self.check(label+': actual frame directory separated by action',directory==f'preview/{skin}/{name}_actual_frames',directory)
        smalls=[Image.open(self.root/directory/f'{i+1:02d}.png').convert('RGBA') for i in range(count)]
        self.smalls[key]=smalls
        equal=[visible_equal(small,self.quantized_small(source,skin)) for small,source in zip(smalls,frames)]
        heights=[im.getchannel('A').getbbox()[3]-im.getchannel('A').getbbox()[1] for im in smalls]
        self.check(label+': fixed affine actual PNGs match source',all(equal),equal)
        self.check(label+': actual heights accurately declared',heights==preview.get('actual_character_heights'),heights)
        if name in NEW and max(heights)>56:self.observations.append({'name':label+' actual height','heights':heights,'note':'Above nominal56 at the explicitly retained original scale; no per-action fitting was applied.'})
        self.evidence[label]={'actual_heights':heights,'source_alpha_bboxes':boxes,'source_rgba_sha256':hashes,'rgb_colors':len(palette)}
        actual=self.gif(f'preview/{skin}/{name}_actual.gif',count,[fps]*count,loop,(600,128))
        large=self.gif(f'preview/{skin}/{name}_4x.gif',count,[fps]*count,loop,(384,384))
        errors=[];large_errors=[];boxes=preview.get('actual_boxes',[])
        valid_boxes=boxes==[[j*120+12,22,96,96] for j in range(5)]
        self.check(label+': five valid character ROIs',valid_boxes,boxes)
        if valid_boxes and len(actual)==count and len(large)==count:
            for i,small in enumerate(smalls):
                mask=small.getchannel('A').point(lambda value:255 if value else 0)
                for box,color in zip(boxes,BACKGROUNDS):
                    x,y,w,h=box;crop=actual[i].crop((x,y,x+w,y+h))
                    expected=Image.alpha_composite(Image.new('RGBA',(96,96),color),small).convert('RGB')
                    errors.append(preview_error(crop,expected,mask))
                dark=Image.alpha_composite(Image.new('RGBA',(96,96),BACKGROUNDS[2]),small).convert('RGB').resize((384,384),Image.Resampling.NEAREST)
                large_errors.append(preview_error(large[i],dark,mask.resize((384,384),Image.Resampling.NEAREST)))
        self.check(label+': actual five-background GIF foreground matches',len(errors)==count*5 and max(errors,default=999)<1,{'maximum_foreground_error':max(errors,default=None)})
        self.check(label+': x4 GIF source content and nearest blocks',len(large_errors)==count and max(large_errors,default=999)<1 and all(nn4(frame) for frame in large),{'maximum_foreground_error':max(large_errors,default=None)})
        onion=Image.open(self.root/f'preview/{skin}/{name}_onion.png')
        self.check(label+': onion PNG exists',onion.format=='PNG' and onion.size==(256,256))

    def synchronized(self,name):
        count,fps,loop=SPEC[name]
        actual=self.gif(f'preview/{name}_compare_actual.gif',count,[fps]*count,loop,(600,384))
        large=self.gif(f'preview/{name}_compare_4x.gif',count,[fps]*count,loop,(1152,416))
        errors=[];blocks=[]
        for i in range(min(count,len(actual),len(large))):
            for j,skin in enumerate(SKINS):
                source=self.smalls[skin,name][i];mask=source.getchannel('A').point(lambda value:255 if value else 0)
                for box,color in zip(self.metas[skin,name]['preview']['actual_boxes'],BACKGROUNDS):
                    x,y,w,h=box;crop=actual[i].crop((x,j*128+y,x+w,j*128+y+h))
                    expected=Image.alpha_composite(Image.new('RGBA',(96,96),color),source).convert('RGB')
                    errors.append(preview_error(crop,expected,mask))
                part=large[i].crop((j*384,32,(j+1)*384,416))
                expected=Image.alpha_composite(Image.new('RGBA',(96,96),BACKGROUNDS[2]),source).convert('RGB').resize((384,384),Image.Resampling.NEAREST)
                errors.append(preview_error(part,expected,mask.resize((384,384),Image.Resampling.NEAREST)));blocks.append(nn4(part))
        self.check(name+': all skins synchronized with source PNGs',len(errors)==count*18 and max(errors,default=999)<1,{'comparisons':len(errors),'maximum_foreground_error':max(errors,default=None)})
        self.check(name+': synchronized x4 nearest-neighbor',len(blocks)==count*3 and all(blocks))

    def current_render(self):
        self.module=import_renderer(self.root/'tools/render.py','dive_round3_current_renderer')
        module=self.module
        for name,(count,fps,loop) in SPEC.items():
            anim=self.anims[name]
            saved=self.json(f'preview/qa/{name}-self-check.json')
            saved_ok=isinstance(saved,dict) and saved.get('passed') is True and saved.get('animation')==name
            if name in OLD:saved_ok=saved_ok and saved.get('timeline_sha256')==digest(self.root/f'rig/animations/{name}.json')
            else:saved_ok=saved_ok and saved.get('fps')==fps and saved.get('loop') is loop
            self.check(name+': current self-check matches action contract',saved_ok,{'timeline_provenance':'Metadata SHA and independently repeated SVG render for every exported sample; old actions also carry a self-check SHA.'})
            anchor=[];root_channels=[]
            for i in range(65):
                pose=module.pose_at(i/64,self.rig,anim)
                root_channels.extend([abs(pose.get('root',0))]+[abs(v) for v in pose.offsets.get('root',[0,0])])
                for angle,scale,mirror in ((50,1,False),(35,.6,False),(65,.8,True)):
                    matrix=module.matrices(pose,self.rig,angle,scale,mirror)['torso']
                    anchor.extend(abs(float(matrix[row,0]*128+matrix[row,1]*128+matrix[row,2]-128)) for row in (0,1))
            self.check(name+': fixed chest at sampled and intermediate poses',max(anchor)<EPS,{'maximum_error_px':max(anchor)})
            self.check(name+': no engine-owned root rotation or translation',max(root_channels)<EPS,{'maximum_root_channel':max(root_channels)})
            for skin in SKINS:
                for i,phase in enumerate(anim['sample_phases']):
                    rendered=module.render_frame(skin,phase,rig=self.rig,anim=anim)
                    self.check(f'{skin}/{name}/{i+1:02d}: current SVG/timeline reproduces source',visible_equal(rendered,self.images[skin,name][i]))
                if loop:
                    self.check(f'{skin}/{name}: periodic raster closure',visible_equal(module.render_frame(skin,0,rig=self.rig,anim=anim),module.render_frame(skin,1,rig=self.rig,anim=anim)))

    def legacy_recolor(self):
        module=import_renderer(self.archive/'tools/render.py','dive_round3_archived_renderer')
        self.oldmodule=module
        self.check('archive renderer uses isolated archive BASE',module.BASE.resolve()==self.archive.resolve())
        recolored=copy.deepcopy(self.oldrig);recolored['outline']['rgb']=RIM
        for skin in SKINS:recolored['skins'][skin]['palette']['rim']=RIM
        controls=[];alpha=[];matches=[];bubble_defaults=[]
        for name in OLD:
            anim=module.load_animation(name)
            for skin in SKINS:
                for i,phase in enumerate(anim['sample_phases']):
                    original=Image.open(self.archive/f'frames/{skin}/{name}/{i+1:02d}.png').convert('RGBA')
                    control=module.render_frame(skin,phase,rig=self.oldrig,anim=anim)
                    controls.append(visible_equal(control,original))
                    now=self.images[skin,name][i]
                    alpha.append(exact(original.getchannel('A').convert('RGB'),now.getchannel('A').convert('RGB')))
                    reference=module.render_frame(skin,phase,rig=recolored,anim=anim)
                    matches.append(visible_equal(reference,now))
                    pose=self.module.pose_at(phase,self.rig,self.anims[name])
                    bubble_defaults.append(abs(pose.get('mouth_bubbles',999))<EPS and pose.offsets.get('mouth_bubbles')==[0,0])
        self.check('archive rendering control reproduces all old54 unchanged',len(controls)==54 and all(controls),{'matches':sum(controls),'total':len(controls),'note':'A failure may indicate font/rasterizer environment drift; do not automatically attribute it to changed motion.'})
        self.check('old54 source alpha geometry unchanged',len(alpha)==54 and all(alpha),{'matches':sum(alpha),'total':len(alpha)})
        self.check('old54 equal archived renderer with only dark-rim recoloring',len(matches)==54 and all(matches),{'matches':sum(matches),'total':len(matches),'transparent_rgb':'ignored where alpha is zero'})
        self.check('old timelines default new bubble bone to zero',len(bubble_defaults)==54 and all(bubble_defaults))

    def wordmark_mask(self,skin):
        svg=ET.fromstring(self.module.compose_svg(skin,1,rig=self.rig,anim=self.anims['turn']))
        def marked(element):
            return 'wordmark' in element.get('id','').lower() or 'wordmark' in element.get('data-symmetry-exempt','').lower()
        def prune(element,selected=False):
            selected=selected or marked(element)
            if selected:
                tag=element.tag.rsplit('}',1)[-1]
                if tag in ('path','rect','ellipse','circle','polygon','polyline','text'):
                    if element.get('fill')!='none':element.set('fill','#FFFFFF')
                    if element.get('stroke') not in (None,'none'):element.set('stroke','#FFFFFF')
                for child in list(element):prune(child,True)
                return True
            kept=False
            for child in list(element):
                if child.get('id') in ('outer-rim','rim-outer-rim') or not prune(child,False):element.remove(child)
                else:kept=True
            return kept
        if not prune(svg):return None
        raw=self.module.cairosvg.svg2png(bytestring=ET.tostring(svg),output_width=768,output_height=768)
        mask=Image.open(io.BytesIO(raw)).convert('RGBA').resize((256,256),Image.Resampling.LANCZOS).getchannel('A')
        mask=mask.point(lambda value:255 if value else 0).filter(ImageFilter.MaxFilter(5))
        return ImageChops.lighter(mask,ImageOps.mirror(mask))

    def special_actions(self):
        for skin in SKINS:
            self.check(skin+': hit last frame exact swim phase0 recovery',visible_equal(self.images[skin,'hit'][-1],self.images[skin,'swim'][0]))
            last=self.metas[skin,'hit']['frames'][-1].get('expressions',{})
            self.check(skin+': hit terminal bubbles cleared',last.get('bubbles',last.get('mouth_bubbles')) in (None,'none','neutral','empty'))
            frame=self.images[skin,'turn'][-1]
            mirror=ImageOps.mirror(frame)
            self.check(skin+': turn03 alpha exactly left/right symmetric',exact(frame.getchannel('A').convert('RGB'),mirror.getchannel('A').convert('RGB')))
            mask=self.wordmark_mask(skin)
            bbox=mask.getbbox() if mask else None
            valid=bool(bbox) and bbox[2]-bbox[0]<=90 and bbox[3]-bbox[1]<=36 and sum(1 for value in raw_pixels(mask) if value)>0
            self.check(skin+': restricted real NABO wordmark exclusion mask',valid,{'bbox':list(bbox) if bbox else None})
            for angle,scale,mirror_mode in ((35,.6,False),(65,.8,True)):
                svg=self.module.compose_svg(skin,1,angle=angle,scale=scale,mirror=mirror_mode,rig=self.rig,anim=self.anims['turn'])
                raw=self.module.cairosvg.svg2png(bytestring=svg.encode(),output_width=768,output_height=768)
                expected=self.module.quantize_sprite(Image.open(io.BytesIO(raw)).convert('RGBA').resize((256,256),Image.Resampling.LANCZOS),self.rig,skin)
                actual=self.module.render_frame(skin,1,angle=angle,scale=scale,mirror=mirror_mode,rig=self.rig,anim=self.anims['turn'])
                self.check(f'{skin}: turn terminal preserves global angle/scale/mirror {angle}/{scale}/{mirror_mode}',visible_equal(expected,actual),{'note':'Noncanonical angle must retain direct projected SVG geometry rather than forcing symmetry about the canvas vertical axis.'})
            if valid:
                visible=frame.getchannel('A').point(lambda value:255 if value else 0)
                compare=ImageChops.multiply(visible,ImageOps.invert(mask))
                self.check(skin+': turn03 body RGB symmetric except NABO wordmark',masked_error(frame,mirror,compare)==0,{'maximum_exclusion_bbox':list(bbox)})
            projection=self.metas[skin,'turn']['frames'][-1].get('view_projection',{})
            self.check(skin+': turn reaches explicit front projection',projection.get('front_mix')==1 and projection.get('facing_angle')==90,projection)
        self.check('gulp swallow event is frame2, 1-based',self.anims['gulp'].get('events',{}).get('swallow')==2,self.anims['gulp'].get('events'))
        self.evidence['new_action_expression_sequences']={name:[expression_state(row.get('expressions',{})) for row in self.metas['a',name]['frames']] for name in NEW}
        self.evidence['out_view_projection']=[row.get('view_projection') for row in self.metas['a','out']['frames']]
        self.observations.append({'name':'out supine pose and turn projection','note':'Action-specific front/relaxed projection is not an engine tilt. Numerical view state does not establish convincing anatomy; inspect PNG contact sheets.'})

    def sequence_expected(self,name):
        if name=='hit':pairs=[('swim',i,False) for i in range(8)]+[('hit',i,False) for i in range(4)]+[('swim',i,False) for i in list(range(1,8))+[0]]
        else:pairs=[('swim',i,False) for i in range(8)]+[('turn',i,False) for i in range(3)]+[('turn',i,True) for i in (1,0)]+[('swim',i,True) for i in list(range(1,8))+[0]]
        return pairs

    def sequences(self):
        for name in ('hit','turn'):
            data=self.json(f'preview/qa/{name}-sequence.json')
            if not isinstance(data,dict):continue
            expected=self.sequence_expected(name);entries=data.get('entries',[])
            pairs=[(entry.get('animation'),entry.get('frame_index'),entry.get('mirror',False)) for entry in entries]
            self.check(name+': explicit fixed-phase sequence ordering',pairs==expected,{'expected':expected,'actual':pairs})
            fps_values=[SPEC[action][1] for action,index,mirror in expected]
            expected_times=durations(fps_values)
            self.check(name+': mixed-fps true cumulative timing',len(entries)==len(expected) and [entry.get('fps') for entry in entries]==fps_values and data.get('durations_ms')==expected_times,{'fps':fps_values,'durations_ms':data.get('durations_ms'),'theoretical_seconds':float(sum((Fraction(1,fps) for fps in fps_values),Fraction(0))),'gif_total_ms':sum(expected_times)})
            actual=self.gif(f'preview/{name}_sequence_actual.gif',len(expected),fps_values,name=='hit',(600,384))
            large=self.gif(f'preview/{name}_sequence_4x.gif',len(expected),fps_values,name=='hit',(1152,416))
            errors=[];blocks=[]
            for i,(action,index,mirror) in enumerate(expected):
                if len(actual)!=len(expected) or len(large)!=len(expected):break
                for j,skin in enumerate(SKINS):
                    source=self.smalls[skin,action][index]
                    if mirror:source=ImageOps.mirror(source)
                    mask=source.getchannel('A').point(lambda value:255 if value else 0)
                    for box,color in zip(self.metas[skin,action]['preview']['actual_boxes'],BACKGROUNDS):
                        x,y,w,h=box;crop=actual[i].crop((x,j*128+y,x+w,j*128+y+h))
                        reference=Image.alpha_composite(Image.new('RGBA',(96,96),color),source).convert('RGB')
                        errors.append(preview_error(crop,reference,mask))
                    part=large[i].crop((j*384,32,(j+1)*384,416))
                    reference=Image.alpha_composite(Image.new('RGBA',(96,96),BACKGROUNDS[2]),source).convert('RGB').resize((384,384),Image.Resampling.NEAREST)
                    errors.append(preview_error(part,reference,mask.resize((384,384),Image.Resampling.NEAREST)));blocks.append(nn4(part))
            self.check(name+': all sequence characters match ordered/mirrored source frames',len(errors)==len(expected)*18 and max(errors,default=999)<1,{'comparisons':len(errors),'maximum_foreground_error':max(errors,default=None),'headers':'excluded; action/frame headers intentionally differ to preserve logical GIF frames'})
            self.check(name+': sequence x4 nearest-neighbor',len(blocks)==len(expected)*3 and all(blocks))

    def manifest_and_scope(self):
        manifest=self.json('manifest.json')
        if isinstance(manifest,dict):
            anims=manifest.get('animations',{})
            self.check('manifest exactly nine authorized actions',set(anims)==set(SPEC))
            self.check('manifest original actual scale retained',manifest.get('preview_scale_to_actual')==SCALE)
            for name,(count,fps,loop) in SPEC.items():
                item=anims.get(name,{})
                expected={skin:[f'frames/{skin}/{name}/{i+1:02d}.png' for i in range(count)] for skin in SKINS}
                self.check(name+': manifest count/fps/loop/all skin paths',item.get('frame_count')==count and item.get('fps')==fps and item.get('loop') is loop and item.get('skin_frames')==expected and item.get('frames')==expected['a'])
            self.check('manifest gulp swallow frame2',anims.get('gulp',{}).get('events',{}).get('swallow')==2)
            self.evidence['manifest_status']=manifest.get('status')
        extra=[]
        for skin in SKINS:
            extra.extend(str(path.relative_to(self.root)) for path in (self.root/'frames'/skin).iterdir() if path.is_dir() and path.name not in SPEC)
        self.check('no optional or later-round action frames produced',not extra,extra)
        scales=[meta['preview']['scale_to_actual'] for meta in self.metas.values()]
        self.check('all27 groups retain exact original scale',len(scales)==27 and all(value==SCALE for value in scales))
        self.check('114 canonical source frames checked',sum(len(group) for group in self.images.values())==114)

    def run(self):
        self.baselines();self.rig_and_sources()
        for name in SPEC:
            for skin in SKINS:self.frame_group(skin,name)
            self.synchronized(name)
        self.current_render();self.legacy_recolor();self.special_actions();self.sequences();self.manifest_and_scope()
        return self.report()

    def report(self):
        passed=all(item['passed'] for item in self.checks)
        return {'schema_version':1,'scope':{name:{'frames':value[0],'fps':value[1],'loop':value[2]} for name,value in SPEC.items()},'passed':passed,'checks_run':len(self.checks),'failures':[item for item in self.checks if not item['passed']],'checks':self.checks,'observations':self.observations,'evidence':self.evidence,'approved_current_spec_baseline':APPROVED_SPECS,'user_animation_review':'pending','limits':['Checks do not replace visual review of anatomy, recognizability, breathing, turn speed or death performance.','No browser file:// playback was performed; the previous denial must not be retried or bypassed. Visual review is limited to explicitly inspected PNGs.','New actions retain the original scale even if their changed poses exceed nominal56px; report actual heights instead of refitting.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);args=parser.parse_args()
    root=args.root.resolve();audit=Audit(root)
    try:report=audit.run()
    except Exception as exc:
        audit.check('validator completed',False,f'{type(exc).__name__}: {exc}');report=audit.report()
    path=root/'preview/qa/round3-validation.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks_run':report['checks_run'],'failures':len(report['failures']),'report':str(path)},ensure_ascii=False))
    for item in report['failures']:print('FAIL:',item['check'])
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
