#!/usr/bin/env python3
"""Independent technical QA for swim, three-stage dash, and the 42-frame sequence.

Only preview/qa/validation.json is written. Renderer functions are imported with
bytecode disabled and evaluated in memory. Naturalness requires visual review.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from PIL import Image, ImageChops, ImageStat

SKINS = ('a', 'b', 'c')
ANIMS = {'swim':8,'dash_in':3,'dash':4,'dash_out':3}
LOOPS = {'swim','dash'}
TIMES = {name:[round((i+1)*100/12)*10-round(i*100/12)*10 for i in range(n)] for name,n in ANIMS.items()}
SEQUENCE = [('swim',i%8) for i in range(16)]+[('dash_in',i) for i in range(3)]+[('dash',i%4) for i in range(12)]+[('dash_out',i) for i in range(3)]+[('swim',i) for i in range(8)]
SEQUENCE_TIMES = [round((i+1)*100/12)*10-round(i*100/12)*10 for i in range(42)]
APPROVED_SPECS = {'ART_BRIEF.md':'a36fe3763f0c2c28139442059224d8824cbe5b79f1a2b3771e505b3f636410b9','CODEX_PROMPTS.md':'44859a2b31628a981ca3ef46a2ef7f3ff566bd23bc5a849bffe62a85ceb50577'}
BG = ['#3FA9D6','#1B5E8C','#0B2A4A','#061528','#04070D']
ALPHA = set(range(0,256,17))
EPS = 1e-9


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rgb_error(a,b):
    if a.size != b.size:
        return float('inf')
    return sum(ImageStat.Stat(ImageChops.difference(a.convert('RGB'),b.convert('RGB'))).mean)/3


def masked_error(a,b,mask):
    if a.size != b.size or mask.size != a.size or not mask.getbbox():
        return float('inf')
    return sum(ImageStat.Stat(ImageChops.difference(a.convert('RGB'),b.convert('RGB')),mask).mean)/3


def exact(a,b):
    return a.size == b.size and a.mode == b.mode and all(hi == 0 for lo,hi in ImageChops.difference(a,b).getextrema())


def nn4(im):
    return im.width % 4 == 0 and im.height % 4 == 0 and exact(im,im.resize((im.width//4,im.height//4),Image.Resampling.NEAREST).resize(im.size,Image.Resampling.NEAREST))


class Audit:
    def __init__(self,root):
        self.root = root
        self.checks, self.observations = [], []
        self.evidence, self.metas, self.images, self.gifs, self.smalls = {}, {}, {}, {}, {}
        self.rig, self.anims, self.module = None, {}, None
        self.foreground_masks = {}
        self.historical_comparisons = []

    def check(self,name,ok,details=None):
        item = {'check':name,'passed':bool(ok)}
        if details is not None:
            item['details'] = details
        self.checks.append(item)
        return bool(ok)

    def json(self,rel):
        try:
            return json.loads((self.root/rel).read_text(encoding='utf-8'))
        except (OSError,ValueError) as exc:
            self.check(f'{rel}: readable JSON',False,str(exc))
            return None

    def baseline(self):
        baseline = self.json('preview/qa/round1-baseline-sha256.json')
        if self.check('round-1 baseline contains original files',isinstance(baseline,dict) and len(baseline)>=30):
            changed = [rel for rel,h in baseline.items() if not (self.root/rel).is_file() or digest(self.root/rel)!=h]
            self.historical_comparisons.append({'name':'round-1 original 43-file baseline','matches':not changed,'checked':len(baseline),'changed_or_missing':changed,'note':'Original specification contents changed externally during v2. Their origin remains unverified; current contents were subsequently approved by the user for this scope. Historical baseline and archived failed report are preserved.'})
            design = {rel:h for rel,h in baseline.items() if rel.startswith('design/')}
            drift = [rel for rel in changed if rel not in APPROVED_SPECS]
            self.check('design: original 41 art files preserved',len(design)==41 and not drift,{'checked':len(design),'changed_or_missing':drift})
            self.evidence['historical_specification_versions'] = [{'file':rel,'original_sha256':baseline.get(rel),'approved_current_sha256':h} for rel,h in APPROVED_SPECS.items()]
        current = {rel:digest(self.root/rel) if (self.root/rel).is_file() else None for rel in APPROVED_SPECS}
        self.check('current specifications match the explicitly approved version',current==APPROVED_SPECS,{'approved_sha256':APPROVED_SPECS,'current_sha256':current})
        for version,expected_count in (('round2_v1',116),('round2_v2',214)):
            archive = self.json(f'history/{version}/snapshot.json')
            files = archive.get('files',{}) if isinstance(archive,dict) else {}
            if isinstance(archive,dict) and 'files' not in archive and all(isinstance(value,str) and len(value)==64 and all(char in '0123456789abcdef' for char in value) for value in archive.values()):
                files = archive
            if self.check(f'{version}: immutable archive snapshot contains expected files',isinstance(files,dict) and len(files)==expected_count,{'expected':expected_count,'found':len(files)}):
                home = self.root/'history'/version
                changed = [rel for rel,h in files.items() if not (home/rel).is_file() or digest(home/rel)!=h]
                self.check(f'{version}: archive preserved byte for byte',not changed,{'checked':len(files),'changed_or_missing':changed})

    def svg(self,rel):
        if not isinstance(rel,str):
            return 'missing SVG path'
        path = (self.root/'rig'/rel).resolve()
        if not path.is_relative_to(self.root/'rig'):
            return 'SVG path escapes rig/'
        try:
            node = ET.parse(path).getroot()
            if node.tag.rsplit('}',1)[-1]!='svg':
                return 'not an SVG root'
            forbidden = [e.tag.rsplit('}',1)[-1] for e in node.iter() if e.tag.rsplit('}',1)[-1] in ('image','filter','linearGradient','radialGradient')]
            if forbidden:
                return 'unexpected raster/filter/gradient: '+','.join(forbidden)
        except (OSError,ET.ParseError) as exc:
            return str(exc)
        return None

    def skeleton(self):
        self.rig = rig = self.json('rig/rig.json')
        if not isinstance(rig,dict):
            return
        self.check('rig: 256 RGBA canvas / fixed chest / 12 fps',rig.get('canvas')==[256,256] and rig.get('anchor')==[128,128] and rig.get('fps')==12)
        bones = rig.get('bones',{})
        required = {'root','torso','neck','head','eyes','mouth','shoulder_near','shoulder_far','pelvis','foot_near','foot_far','shin_foot_near','shin_foot_far'}
        if not self.check('shared articulated skeleton contains required bones',isinstance(bones,dict) and required<=set(bones),sorted(bones)):
            return
        bad_pivots, bad_chains = [], []
        for name,spec in bones.items():
            pivot = spec.get('pivot')
            if not isinstance(pivot,list) or len(pivot)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in pivot):
                bad_pivots.append(name)
            seen,current = set(),name
            while current is not None:
                if current in seen or current not in bones:
                    bad_chains.append(name)
                    break
                seen.add(current)
                current = bones[current].get('parent')
        self.check('every bone has a fixed finite pivot',not bad_pivots,bad_pivots)
        self.check('bone hierarchy resolves without cycles',not bad_chains,bad_chains)
        self.check('head follows articulated neck chain',bones['head'].get('parent')=='neck' and bones['neck'].get('parent')=='torso')
        self.check('both shoes have ankle child bones',all(bones[f'foot_{side}'].get('parent')==f'shin_foot_{side}' for side in ('near','far')))
        order = rig.get('draw_order',[])
        self.check('shared drawing slots resolve to unique bones',len(order)>=18 and len(order)==len(set(order)) and set(order)<=set(bones))
        skins = rig.get('skins',{})
        self.check('all three retained skins exist',set(skins)==set(SKINS))
        for skin in SKINS:
            slots = skins.get(skin,{}).get('slots',{})
            self.check(f'{skin}: skin has identical drawing slots',set(slots)==set(order))
            bad = {slot:self.svg(rel) for slot,rel in slots.items() if rel is not None}
            bad = {k:v for k,v in bad.items() if v}
            self.check(f'{skin}: vector component assets resolve',not bad,bad)
            self.check(f'{skin}: shoes are independent SVG assets',all(slots.get(f'foot_{side}') and slots.get(f'foot_{side}')!=slots.get(f'shin_foot_{side}') for side in ('near','far')))
            for name,mapping in skins[skin].get('animation_overrides',{}).items():
                failures = {slot:self.svg(rel) for slot,rel in mapping.items() if rel is not None and self.svg(rel)}
                self.check(f'{skin}/{name}: skin-mapped override assets resolve',name in ANIMS and set(mapping)<=set(order) and not failures,failures)
            arm_slots = ['upper_arm_near','upper_arm_far','forearm_hand_near','forearm_hand_far','hand_near','hand_far']
            self.check(f'{skin}: both actions share fixed arm and hand SVG assets',all(skins[skin].get('animation_overrides',{}).get(name,{}).get(slot,slots.get(slot))==slots.get(slot) for name in ANIMS for slot in arm_slots))
        for name,action_order in rig.get('action_draw_orders',{}).items():
            self.check(f'{name}: action draw order uses same shared slots',name in ANIMS and len(action_order)==len(set(action_order)) and set(action_order)==set(order))
        self.evidence['bone_count'] = len(bones)
        self.evidence['shared_skeleton_sha256'] = hashlib.sha256(json.dumps(bones,sort_keys=True).encode()).hexdigest()
        self.evidence['bone_pivots'] = {k:v['pivot'] for k,v in bones.items()}
        for name,count in ANIMS.items():
            anim = self.json(f'rig/animations/{name}.json')
            if not isinstance(anim,dict):
                continue
            self.anims[name] = anim
            keys = anim.get('keyframes',[])
            phases = [k.get('phase') for k in keys]
            complete = len(keys)>=2 and all(set(k.get('rotations',{}))==set(bones) and set(k.get('translations',{}))==set(bones) for k in keys)
            self.check(f'{name}: complete shared rotation and translation tracks',complete)
            self.check(f'{name}: frame count / exact 12 fps / correct loop flag',anim.get('frame_count')==count and anim.get('fps')==12 and anim.get('loop') is (name in LOOPS))
            samples = anim.get('sample_phases')
            self.check(f'{name}: export phases exclude hidden terminal endpoint',samples==[i/count for i in range(count)],samples)
            phase_ok = phases and phases[0]==0 and phases==sorted(set(phases)) and all(isinstance(x,(int,float)) and 0<=x<=1 for x in phases)
            if name in LOOPS:
                phase_ok = phase_ok and phases[-1]<1
            else:
                phase_ok = phase_ok and phases[-1]==1
            self.check(f'{name}: correct loop or bounded transition key domain',phase_ok,phases)
            interpolation = anim.get('interpolation','').lower()
            nonlinear = any(word in interpolation for word in ('hermite','cubic','smooth','ease'))
            self.check(f'{name}: explicit nonlinear interpolation',nonlinear and (name not in LOOPS or 'periodic' in interpolation),interpolation)
            root_zero = all(all(abs(k.get('rotations',{}).get(b,999))<EPS and k.get('translations',{}).get(b)==[0,0] for b in ('root','torso')) for k in keys)
            self.check(f'{name}: no root/chest translation or whole-body tilt',complete and root_zero)
            secondary = anim.get('secondary',{})
            if name in LOOPS:
                self.check(f'{name}: explicitly delayed secondary motion',secondary.get('lag_frames',0)>0 and bool(secondary.get('nodes')),secondary)
            if complete:
                ranges = {b:max(k['rotations'][b] for k in keys)-min(k['rotations'][b] for k in keys) for b in bones}
                self.evidence[f'{name}_local_rotation_ranges_deg'] = ranges
                if name in ('swim','dash'):
                    self.check(f'{name}: independent ankle rotation varies',all(ranges[f'foot_{side}']>1e-6 for side in ('near','far')), {f'foot_{side}':ranges[f'foot_{side}'] for side in ('near','far')})
            if name not in LOOPS:
                expected = {'from':{'animation':'swim' if name=='dash_in' else 'dash','phase':0},'to':{'animation':'dash' if name=='dash_in' else 'swim','phase':0}}
                transition = anim.get('transition',{})
                self.check(f'{name}: explicit fixed source and destination phase',all(transition.get(edge)==reference for edge,reference in expected.items()),transition)
                self.check(f'{name}: hidden terminal endpoint and fixed-phase policy',transition.get('hidden_endpoint_phase')==1 and transition.get('fixed_phase_only') is True)
            overrides = anim.get('asset_overrides',{})
            paths = []
            def collect(value):
                if isinstance(value,str) and value.endswith('.svg'):
                    paths.append(value)
                elif isinstance(value,dict):
                    for child in value.values():collect(child)
            collect(overrides)
            failures = {path:self.svg(path) for path in paths if self.svg(path)}
            self.check(f'{name}: override SVG assets resolve',not failures,failures)
        self.check('only authorized four timelines exist',sorted(p.name for p in (self.root/'rig/animations').glob('*.json') if not p.name.startswith('._'))==sorted(name+'.json' for name in ANIMS))

    def gif(self,rel,anim,geometry,expected_count=None,expected_durations=None,expected_loop="auto"):
        try:
            im = Image.open(self.root/rel)
            frames,durations = [],[]
            loop = im.info.get('loop')
            count = im.n_frames
            for i in range(count):
                im.seek(i)
                frames.append(im.convert('RGB').copy())
                durations.append(im.info.get('duration'))
            wanted_count = expected_count if expected_count is not None else ANIMS[anim]
            wanted_durations = expected_durations if expected_durations is not None else TIMES[anim]
            wanted_loop = (0 if anim in LOOPS else None) if expected_loop=='auto' else expected_loop
            self.check(f'{rel}: frame count / 12fps quantization / preview loop policy',count==wanted_count and durations==wanted_durations and loop==wanted_loop,{'frames':count,'durations_ms':durations,'cycle_ms':sum(durations),'loop':loop,'expected_loop':wanted_loop})
            self.check(f'{rel}: preview geometry',im.size==geometry,list(im.size))
            self.gifs[rel] = frames
            return frames
        except (OSError,EOFError) as exc:
            self.check(f'{rel}: readable GIF',False,str(exc))
            return []

    def frames(self,skin,anim,count):
        key = f'{skin}/{anim}'
        folder = self.root/f'frames/{key}'
        names = [f'{i+1:02d}.png' for i in range(count)]
        self.check(f'{key}: exact canonical frame files',sorted(p.name for p in folder.glob('*.png') if not p.name.startswith('._'))==names)
        images,boxes,hashes,palette,alphas,counts = [],[],[],set(),set(),[]
        for name in names:
            try:
                raw = Image.open(folder/name)
                self.check(f'{key}/{name}: 256x256 RGBA PNG',raw.size==(256,256) and raw.mode=='RGBA' and raw.format=='PNG')
                im = raw.convert('RGBA')
                images.append(im)
                hashes.append(hashlib.sha256(im.tobytes()).hexdigest())
                pixels = list(im.get_flattened_data() if hasattr(im,'get_flattened_data') else im.getdata())
                colors = {p[:3] for p in pixels if p[3]>0}
                palette.update(colors)
                counts.append(len(colors))
                alphas.update(p[3] for p in pixels)
                bbox = im.getchannel('A').getbbox()
                boxes.append(list(bbox) if bbox else None)
            except OSError as exc:
                self.check(f'{key}/{name}: readable PNG',False,str(exc))
        self.images[key] = images
        self.check(f'{key}: all frames distinct',len(hashes)==count and len(set(hashes))==count)
        self.check(f'{key}: <=32 visible RGB colors for whole cycle',len(images)==count and len(palette)<=32,{'per_frame':counts,'cycle':len(palette)})
        self.check(f'{key}: exact 16-level alpha grid',bool(images) and alphas<=ALPHA,sorted(alphas))
        self.check(f'{key}: no alpha clipping or empty frames',len(boxes)==count and all(b and min(b[:2])>0 and max(b[2:])<256 for b in boxes),boxes)
        if len(images)==count:
            dark = [Image.alpha_composite(Image.new('RGBA',im.size,(0,0,0,255)),im).convert('RGB') for im in images]
            differences = [rgb_error(dark[i],dark[(i+1)%count]) for i in range(count)]
            self.observations.append({'name':key+' successive pixel differences','values':differences,'seam':differences[-1],'note':'Reported for visual review; magnitude alone cannot establish natural motion.'})
        self.evidence[key] = {'rgba_sha256':hashes,'visible_bboxes':boxes,'palette':['#%02X%02X%02X'%c for c in sorted(palette)]}
        meta = self.json(f'frames/{key}/metadata.json')
        if isinstance(meta,dict):
            self.metas[key] = meta
            rows = meta.get('frames',[])
            anchors = [r.get('anchor_world',[]) for r in rows]
            error = max((abs(v-128) for a in anchors for v in a),default=float('inf'))
            self.check(f'{key}: metadata action timing and loop flag',meta.get('fps')==12 and meta.get('frame_count')==count and meta.get('loop') is (anim in LOOPS))
            self.check(f'{key}: fixed metadata chest anchor',meta.get('anchor')==[128,128] and len(anchors)==count and all(len(a)==2 for a in anchors) and error<EPS,{'maximum_error_px':error})
            self.check(f'{key}: metadata bounds and phases match canonical PNGs',[r.get('visible_bbox') for r in rows]==boxes and [r.get('phase') for r in rows]==[i/count for i in range(count)])
            self.check(f'{key}: shared skeleton and current timeline hashes',meta.get('shared_skeleton_sha256')==self.evidence.get('shared_skeleton_sha256') and meta.get('timeline_sha256')==digest(self.root/f'rig/animations/{anim}.json'))
        actual = self.gif(f'preview/{skin}/{anim}_actual.gif',anim,(600,128))
        large = self.gif(f'preview/{skin}/{anim}_4x.gif',anim,(384,384))
        self.check(f'{key}: true nearest-neighbor x4 blocks',len(large)==count and all(nn4(im) for im in large))
        if isinstance(meta,dict):
            self.actual(skin,anim,meta,actual,large)
        try:
            onion = Image.open(self.root/f'preview/{skin}/{anim}_onion.png')
            self.check(f'{key}: onion PNG exists',onion.format=='PNG' and onion.size==(256,256))
        except OSError as exc:
            self.check(f'{key}: onion PNG exists',False,str(exc))

    def actual(self,skin,anim,meta,frames,large):
        key = f'{skin}/{anim}'
        count = ANIMS[anim]
        preview = meta.get('preview',{})
        boxes = preview.get('actual_boxes',[])
        roi_ok = len(boxes)==5 and all(isinstance(b,list) and len(b)==4 and all(isinstance(x,int) for x in b) for b in boxes)
        if roi_ok:
            roi_ok = all(x>=0 and y>=0 and w==96 and h==96 and x+w<=600 and y+h<=128 for x,y,w,h in boxes)
            for i,(x,y,w,h) in enumerate(boxes):
                for xx,yy,ww,hh in boxes[i+1:]:
                    roi_ok &= x+w<=xx or xx+ww<=x or y+h<=yy or yy+hh<=y
        self.check(f'{key}: five distinct in-bounds 96px preview ROIs',roi_ok,boxes)
        self.check(f'{key}: all five required backgrounds declared',preview.get('backgrounds')==BG)
        scale = preview.get('scale_to_actual',0)
        self.check(f'{key}: valid fixed scale and 96px canvas',0<scale<1 and preview.get('actual_frame_canvas')==[96,96] and preview.get('actual_anchor')==[48,48],scale)
        directory = preview.get('actual_frames_dir')
        path_ok = isinstance(directory,str) and directory==f'preview/{skin}/{anim}_actual_frames'
        self.check(f'{key}: actual frame storage separated by action',path_ok,directory)
        if not (path_ok and scale>0 and len(self.images[key])==count):
            return
        colors = [tuple(int(c[j:j+2],16) for j in (1,3,5)) for c in self.rig['skins'][skin]['palette'].values()]
        palette = Image.new('P',(1,1))
        palette.putpalette([v for c in colors+[colors[-1]]*(256-len(colors)) for v in c])
        stored,heights,matched = [],[],[]
        for i,source in enumerate(self.images[key]):
            im = Image.open(self.root/directory/f'{i+1:02d}.png').convert('RGBA')
            stored.append(im)
            box = im.getchannel('A').getbbox()
            heights.append(box[3]-box[1] if box else 0)
            fixed = source.transform((96,96),Image.Transform.AFFINE,(1/scale,0,128-48/scale,0,1/scale,128-48/scale),Image.Resampling.BICUBIC)
            expected = fixed.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE).convert('RGB')
            expected.putalpha(fixed.getchannel('A').point(lambda v:round(v/17)*17))
            matched.append(exact(im,expected))
        self.smalls[key] = stored
        self.check(f'{key}: saved actual sprites match fixed chest-centered affine',all(matched),matched)
        self.check(f'{key}: actual character heights <=56 and metadata matches',all(0<h<=56 for h in heights) and heights==preview.get('actual_character_heights'),heights)
        self.evidence[key]['actual_character_heights'] = heights
        bg_ok,errors,visible_heights,large_errors = True,[],[],[]
        foreground_errors,large_foreground_errors,actual_masks,large_masks = [],[],[],[]
        if roi_ok and len(frames)==count and len(large)==count:
            for i,frame in enumerate(frames):
                row = []
                mask = stored[i].getchannel('A').point(lambda v:255 if v else 0)
                full_mask = Image.new('L',(600,128),0)
                for box,color in zip(boxes,BG):
                    x,y,w,h = box
                    crop = frame.crop((x,y,x+w,y+h))
                    bg = tuple(int(color[j:j+2],16) for j in (1,3,5))
                    corner = crop.getpixel((0,0))
                    bg_ok &= max(abs(a-b) for a,b in zip(corner,bg))<=3
                    bbox = ImageChops.difference(crop,Image.new('RGB',crop.size,corner)).getbbox()
                    row.append(bbox[3]-bbox[1] if bbox else 0)
                    expected = Image.alpha_composite(Image.new('RGBA',(96,96),bg+(255,)),stored[i]).convert('RGB')
                    errors.append(rgb_error(crop,expected))
                    foreground_errors.append(masked_error(crop,expected,mask))
                    full_mask.paste(mask,(x,y))
                visible_heights.append(row)
                dark = Image.alpha_composite(Image.new('RGBA',(96,96),BG[2]),stored[i]).convert('RGB')
                expected4 = dark.resize((384,384),Image.Resampling.NEAREST)
                mask4 = mask.resize((384,384),Image.Resampling.NEAREST)
                large_errors.append(rgb_error(large[i],expected4))
                large_foreground_errors.append(masked_error(large[i],expected4,mask4))
                actual_masks.append(full_mask)
                large_masks.append(mask4)
        self.foreground_masks[f'preview/{skin}/{anim}_actual.gif'] = actual_masks
        self.foreground_masks[f'preview/{skin}/{anim}_4x.gif'] = large_masks
        self.check(f'{key}: five backgrounds verified in GIF pixels',bg_ok and len(errors)==count*5)
        self.check(f'{key}: GIF contains matching actual-scale character frames',len(errors)==count*5 and max(errors,default=999)<2,{'maximum_mean_rgb_error':max(errors,default=None),'gif_heights':visible_heights})
        self.check(f'{key}: x4 GIF matches actual sprites',len(large_errors)==count and max(large_errors,default=999)<2,{'maximum_mean_rgb_error':max(large_errors,default=None)})
        self.check(f'{key}: GIF foreground matches actual-scale source',len(foreground_errors)==count*5 and max(foreground_errors,default=999)<1,{'maximum_foreground_mean_rgb_error':max(foreground_errors,default=None)})
        self.check(f'{key}: x4 foreground matches source',len(large_foreground_errors)==count and max(large_foreground_errors,default=999)<1,{'maximum_foreground_mean_rgb_error':max(large_foreground_errors,default=None)})

    def composites(self):
        for anim,count in ANIMS.items():
            actual = self.gif(f'preview/{anim}_compare_actual.gif',anim,(600,384))
            large = self.gif(f'preview/{anim}_compare_4x.gif',anim,(1152,416))
            errors,blocks,foreground_errors = [],[],[]
            for i in range(min(len(actual),len(large))):
                for j,skin in enumerate(SKINS):
                    single = self.gifs.get(f'preview/{skin}/{anim}_actual.gif',[])
                    single4 = self.gifs.get(f'preview/{skin}/{anim}_4x.gif',[])
                    if len(single)!=count or len(single4)!=count:
                        continue
                    a = actual[i].crop((0,j*128,600,(j+1)*128))
                    b = large[i].crop((j*384,32,(j+1)*384,416))
                    errors += [rgb_error(a,single[i]),rgb_error(b,single4[i])]
                    masks = self.foreground_masks.get(f'preview/{skin}/{anim}_actual.gif',[])
                    masks4 = self.foreground_masks.get(f'preview/{skin}/{anim}_4x.gif',[])
                    if len(masks)==count and len(masks4)==count:
                        foreground_errors += [masked_error(a,single[i],masks[i]),masked_error(b,single4[i],masks4[i])]
                    blocks.append(nn4(b))
            self.check(f'{anim}: synchronized skin composites match same-index frames',len(errors)==count*6 and max(errors,default=999)<2,{'maximum_mean_rgb_error':max(errors,default=None),'comparisons':len(errors)})
            self.check(f'{anim}: synchronized x4 sprite blocks are nearest-neighbor',len(blocks)==count*3 and all(blocks))
            self.check(f'{anim}: synchronized foreground content matches',len(foreground_errors)==count*6 and max(foreground_errors,default=999)<1,{'maximum_foreground_mean_rgb_error':max(foreground_errors,default=None)})
            actual_masks,large_masks = [],[]
            for i in range(count):
                mask = Image.new('L',(600,384),0)
                mask4 = Image.new('L',(1152,416),0)
                for j,skin in enumerate(SKINS):
                    masks = self.foreground_masks.get(f'preview/{skin}/{anim}_actual.gif',[])
                    masks4 = self.foreground_masks.get(f'preview/{skin}/{anim}_4x.gif',[])
                    if len(masks)==count and len(masks4)==count:
                        mask.paste(masks[i],(0,j*128))
                        mask4.paste(masks4[i],(j*384,32))
                actual_masks.append(mask)
                large_masks.append(mask4)
            self.foreground_masks[f'preview/{anim}_compare_actual.gif'] = actual_masks
            self.foreground_masks[f'preview/{anim}_compare_4x.gif'] = large_masks
        actual = self.gif('preview/swim_dash_compare_actual.gif','swim',(1200,384))
        large = self.gif('preview/swim_dash_compare_4x.gif','swim',(2304,416))
        errors,foreground_errors = [],[]
        for i in range(min(len(actual),len(large))):
            for j,anim in enumerate(('swim','dash')):
                index = i%ANIMS[anim]
                a = self.gifs.get(f'preview/{anim}_compare_actual.gif',[])
                b = self.gifs.get(f'preview/{anim}_compare_4x.gif',[])
                if len(a)==ANIMS[anim] and len(b)==ANIMS[anim]:
                    aa = actual[i].crop((j*600,0,(j+1)*600,384))
                    bb = large[i].crop((j*1152,0,(j+1)*1152,416))
                    errors += [rgb_error(aa,a[index]),rgb_error(bb,b[index])]
                    mask = self.foreground_masks[f'preview/{anim}_compare_actual.gif'][index]
                    mask4 = self.foreground_masks[f'preview/{anim}_compare_4x.gif'][index]
                    foreground_errors += [masked_error(aa,a[index],mask),masked_error(bb,b[index],mask4)]
        self.check('side-by-side swim/dash composites use dash frame i%4',len(errors)==32 and max(errors,default=999)<2,{'maximum_mean_rgb_error':max(errors,default=None),'comparisons':len(errors)})
        self.check('side-by-side foreground frames remain synchronized',len(foreground_errors)==32 and max(foreground_errors,default=999)<1,{'maximum_foreground_mean_rgb_error':max(foreground_errors,default=None)})
        metas = list(self.metas.values())
        scales = [m.get('preview',{}).get('scale_to_actual') for m in metas]
        boxes = [m.get('preview',{}).get('source_union_bbox') for m in metas]
        all_boxes = [im.getchannel('A').getbbox() for group in self.images.values() for im in group]
        union = [min(b[0] for b in all_boxes),min(b[1] for b in all_boxes),max(b[2] for b in all_boxes),max(b[3] for b in all_boxes)] if all_boxes else None
        self.check('all four actions and all skins use one fixed global actual scale',len(metas)==12 and len(set(scales))==1,scales)
        self.check('metadata source union spans all four actions and all skins',len(boxes)==12 and all(box==union for box in boxes),{'computed_union':union,'metadata_unions':boxes})
        heights = [h for key,data in self.evidence.items() if '/' in key for h in data.get('actual_character_heights',[])]
        self.check('global actual character height maximum is 56px',len(heights)==54 and max(heights,default=0)==56 and all(0<h<=56 for h in heights),{'count':len(heights),'min':min(heights,default=None),'max':max(heights,default=None)})

    def sequence(self):
        data = self.json('preview/qa/dash-sequence.json')
        entries = data.get('entries',[]) if isinstance(data,dict) else []
        pairs = [(entry.get('animation'),entry.get('frame_index')) for entry in entries]
        self.check('sequence: exactly swim2 -> in -> dash3 -> out -> swim1',pairs==SEQUENCE,{'logical_frames':len(pairs),'entries':pairs})
        self.check('sequence: exact 42-frame 12fps schedule is 3500ms',isinstance(data,dict) and data.get('fps')==12 and data.get('durations_ms')==SEQUENCE_TIMES and sum(SEQUENCE_TIMES)==3500, data.get('durations_ms') if isinstance(data,dict) else None)
        self.evidence['sequence_phase_policy'] = data.get('phase_policy') if isinstance(data,dict) else None
        self.evidence['sequence_manifest_sha256'] = digest(self.root/'preview/qa/dash-sequence.json') if isinstance(data,dict) else None
        for skin in SKINS:
            actual = self.gif(f'preview/{skin}/dash_sequence_actual.gif','sequence',(600,128),42,SEQUENCE_TIMES,0)
            large = self.gif(f'preview/{skin}/dash_sequence_4x.gif','sequence',(384,384),42,SEQUENCE_TIMES,0)
            errors,foreground = [],[]
            for i,(anim,index) in enumerate(SEQUENCE):
                if len(actual)!=42 or len(large)!=42:break
                a,b = self.gifs[f'preview/{skin}/{anim}_actual.gif'][index],self.gifs[f'preview/{skin}/{anim}_4x.gif'][index]
                mask,mask4 = self.foreground_masks[f'preview/{skin}/{anim}_actual.gif'][index],self.foreground_masks[f'preview/{skin}/{anim}_4x.gif'][index]
                errors += [rgb_error(actual[i],a),rgb_error(large[i],b)]
                foreground += [masked_error(actual[i],a,mask),masked_error(large[i],b,mask4)]
            self.check(f'{skin}: all 42 sequence frames match independent source ordering',len(errors)==84 and max(errors,default=999)<2 and len(foreground)==84 and max(foreground,default=999)<1,{'comparisons':len(errors),'maximum_rgb_error':max(errors,default=None),'maximum_foreground_error':max(foreground,default=None)})
            self.check(f'{skin}: sequence x4 uses exact nearest-neighbor blocks',len(large)==42 and all(nn4(frame) for frame in large))
        actual = self.gif('preview/dash_sequence_actual.gif','sequence',(600,384),42,SEQUENCE_TIMES,0)
        large = self.gif('preview/dash_sequence_4x.gif','sequence',(1152,416),42,SEQUENCE_TIMES,0)
        errors,foreground,blocks = [],[],[]
        for i,(anim,index) in enumerate(SEQUENCE):
            if len(actual)!=42 or len(large)!=42:break
            for j,skin in enumerate(SKINS):
                a = actual[i].crop((0,j*128,600,(j+1)*128))
                b = large[i].crop((j*384,32,(j+1)*384,416))
                reference = self.gifs[f'preview/{skin}/{anim}_actual.gif'][index]
                reference4 = self.gifs[f'preview/{skin}/{anim}_4x.gif'][index]
                mask = self.foreground_masks[f'preview/{skin}/{anim}_actual.gif'][index]
                mask4 = self.foreground_masks[f'preview/{skin}/{anim}_4x.gif'][index]
                errors += [rgb_error(a,reference),rgb_error(b,reference4)]
                foreground += [masked_error(a,reference,mask),masked_error(b,reference4,mask4)]
                blocks.append(nn4(b))
        self.check('sequence: 42 synchronized frames match all three skins',len(errors)==252 and max(errors,default=999)<2 and len(foreground)==252 and max(foreground,default=999)<1,{'comparisons':len(errors),'maximum_rgb_error':max(errors,default=None),'maximum_foreground_error':max(foreground,default=None)})
        self.check('sequence: every synchronized x4 block is nearest-neighbor',len(blocks)==126 and all(blocks))

    def renderer(self):
        path = self.root/'tools/render.py'
        help_result = subprocess.run([sys.executable,'-B',str(path),'--help'],cwd=self.root,capture_output=True,text=True,timeout=30)
        self.check('renderer CLI exposes all four actions / skin / transforms',help_result.returncode==0 and all(x in help_result.stdout for x in ('--skin','--anim','swim','dash_in','dash','dash_out','all','--angle','--scale','--mirror')))
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('dive_transition_renderer',path)
        self.module = module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rig = module.load_rig()
        def pose_difference(a,b):
            rotation = max(abs(a[k]-b[k]) for k in rig['bones'])
            translation = max(abs(a.offsets[k][axis]-b.offsets[k][axis]) for k in rig['bones'] for axis in (0,1))
            cloth = abs(getattr(a,'cloth_mix',0)-getattr(b,'cloth_mix',0))
            return {'rotation_deg':rotation,'translation_px':translation,'cloth_mix':cloth}
        for name,count in ANIMS.items():
            anim = module.load_animation(name)
            saved = self.json(f'preview/qa/{name}-self-check.json')
            self.check(f'{name}: current renderer self-check report',isinstance(saved,dict) and saved.get('passed') is True and saved.get('timeline_sha256')==digest(self.root/f'rig/animations/{name}.json'),saved)
            p0,p1 = module.pose_at(0,rig,anim),module.pose_at(1,rig,anim)
            self.check(f'{name}: Pose carries all local translations',set(getattr(p0,'offsets',{}))==set(rig['bones']))
            if name in LOOPS:
                closure = pose_difference(p0,p1)
                step = 1e-7
                pl,pr = module.pose_at(-step,rig,anim),module.pose_at(step,rig,anim)
                velocity = max(abs((p0[k]-pl[k])/step-(pr[k]-p0[k])/step) for k in p0)
                shift_velocity = max(abs((p0.offsets[k][axis]-pl.offsets[k][axis])/step-(pr.offsets[k][axis]-p0.offsets[k][axis])/step) for k in p0 for axis in (0,1))
                self.check(f'{name}: fresh periodic pose closure and C1 velocity',max(closure.values())<EPS and velocity<.1 and shift_velocity<.1,dict(closure,rotation_velocity_gap_deg_cycle=velocity,translation_velocity_gap_px_cycle=shift_velocity))
            else:
                low = pose_difference(module.pose_at(-.25,rig,anim),p0)
                high = pose_difference(module.pose_at(1.25,rig,anim),p1)
                self.check(f'{name}: non-loop phases clamp to endpoints',max(low.values())<EPS and max(high.values())<EPS,{'below_zero':low,'above_one':high})
            anchor_error,body_error,ankle_error = [],[],[]
            head_matrices,neck_matrices,head_positions = [],[],[]
            segment_lengths = {side:{'upper':[],'forearm':[]} for side in ('near','far')}
            stable_bones = ['root','torso','neck','head','shoulder_near','shoulder_far','upper_arm_near','upper_arm_far','forearm_hand_near','forearm_hand_far','hand_near','hand_far','pelvis','thigh_near','thigh_far']
            stable_errors = []
            initial = module.matrices(p0,rig)
            for i in range(65):
                pose = module.pose_at(i/64,rig,anim)
                matrix = module.matrices(pose,rig)
                head_matrices.append(matrix['head']);neck_matrices.append(matrix['neck'])
                hp = rig['bones']['head']['pivot']
                head_positions.append([float(matrix['head'][row,0]*hp[0]+matrix['head'][row,1]*hp[1]+matrix['head'][row,2]) for row in (0,1)])
                body_error += [abs(float(matrix[b][row,col]-initial[b][row,col])) for b in ('root','torso') for row in range(3) for col in range(3)]
                if name=='dash':
                    stable_errors += [abs(float(matrix[b][row,col]-initial[b][row,col])) for b in stable_bones for row in range(3) for col in range(3)]
                for side in ('near','far'):
                    def world_point(bone,point):
                        mm = matrix[bone]
                        return [float(mm[row,0]*point[0]+mm[row,1]*point[1]+mm[row,2]) for row in (0,1)]
                    shoulder = world_point(f'upper_arm_{side}',rig['bones'][f'upper_arm_{side}']['pivot'])
                    elbow = world_point(f'forearm_hand_{side}',rig['bones'][f'forearm_hand_{side}']['pivot'])
                    wrist = world_point(f'hand_{side}',rig['bones'][f'hand_{side}']['pivot'])
                    segment_lengths[side]['upper'].append(math.dist(shoulder,elbow))
                    segment_lengths[side]['forearm'].append(math.dist(elbow,wrist))
                    point = rig['bones'][f'foot_{side}']['pivot']
                    pm,cm = matrix[f'shin_foot_{side}'],matrix[f'foot_{side}']
                    ankle_error += [abs(float((pm[row,0]-cm[row,0])*point[0]+(pm[row,1]-cm[row,1])*point[1]+pm[row,2]-cm[row,2])) for row in (0,1)]
                for angle,scale,mirror in ((50,1,False),(35,.6,False),(65,.8,True)):
                    mm = module.matrices(pose,rig,angle,scale,mirror)['torso']
                    anchor_error += [abs(float(mm[row,0]*128+mm[row,1]*128+mm[row,2]-128)) for row in (0,1)]
            motion = lambda matrices:max(abs(float(m[row,col]-matrices[0][row,col])) for m in matrices for row in range(3) for col in range(3))
            head_motion,neck_motion = motion(head_matrices),motion(neck_matrices)
            self.check(f'{name}: fixed chest under 65 phases and three transforms',max(anchor_error)<EPS,{'maximum_error_px':max(anchor_error)})
            self.check(f'{name}: root and torso world matrices remain static',max(body_error)<EPS,{'maximum_matrix_error':max(body_error)})
            if name=='swim':
                self.check('swim: head and neck move independently of fixed chest',head_motion>1e-6 and neck_motion>1e-6,{'head_matrix_change':head_motion,'neck_matrix_change':neck_motion,'head_pivot_x_span':max(p[0] for p in head_positions)-min(p[0] for p in head_positions),'head_pivot_y_span':max(p[1] for p in head_positions)-min(p[1] for p in head_positions),'note':'Nonzero motion is not a naturalness judgment.'})
            elif name=='dash':
                self.check('dash: head, shoulders, arms, hands and pelvis are stable',max(stable_errors)<EPS,{'bones':stable_bones,'maximum_matrix_change':max(stable_errors)})
            self.check(f'{name}: ankle pivots stay attached to lower legs',max(ankle_error)<EPS,{'maximum_error_px':max(ankle_error)})
            spans = {side:{segment:max(values)-min(values) for segment,values in data.items()} for side,data in segment_lengths.items()}
            self.check(f'{name}: fixed arm segment lengths throughout action',all(span<EPS for data in spans.values() for span in data.values()),{'length_spans_px':spans})
            for skin in SKINS:
                im0 = module.render_frame(skin,0,rig=rig,anim=anim)
                if name in LOOPS:
                    self.check(f'{skin}/{name}: exact phase-0/1 loop raster equality',exact(im0,module.render_frame(skin,1,rig=rig,anim=anim)))
                current = self.images.get(f'{skin}/{name}',[])
                for i in range(count):
                    rendered = im0 if i==0 else module.render_frame(skin,i/count,rig=rig,anim=anim)
                    self.check(f'{skin}/{name}/{i+1:02d}: canonical PNG equals current SVG/rig/timeline',len(current)==count and exact(rendered,current[i]))
        for name in ('dash_in','dash_out'):
            anim = module.load_animation(name)
            contract = anim['transition']
            for edge,phase in (('from',0),('to',1)):
                target = contract[edge]
                reference = module.load_animation(target['animation'])
                error = pose_difference(module.pose_at(phase,rig,anim),module.pose_at(target['phase'],rig,reference))
                self.check(f'{name}: {edge} hidden endpoint matches fixed reference pose',max(error.values())<EPS,error)
                for skin in SKINS:
                    a = module.render_frame(skin,phase,rig=rig,anim=anim)
                    b = module.render_frame(skin,target['phase'],rig=rig,anim=reference)
                    self.check(f'{skin}/{name}: {edge} endpoint exact SVG raster match including cloth',exact(a,b))
            self.observations.append({'name':name+' continuity contract','claim':'Exact C0 pose and raster endpoint matching with easing; no claim of C1 velocity across different actions.'})

    def manifest(self):
        manifest = self.json('manifest.json')
        if not isinstance(manifest,dict):return
        self.check('manifest: fixed canvas/anchor/fps/target',manifest.get('canvas')==[256,256] and manifest.get('anchor')==[128,128] and manifest.get('fps')==12 and manifest.get('nabo_target_height_px')==56)
        mapping = manifest.get('animations',{})
        self.check('manifest: exactly four authorized actions',set(mapping)==set(ANIMS))
        for name,count in ANIMS.items():
            spec = mapping.get(name,{})
            expected = {skin:[f'frames/{skin}/{name}/{i+1:02d}.png' for i in range(count)] for skin in SKINS}
            self.check(f'manifest {name}: loop/timing and all skin paths correct',spec.get('loop') is (name in LOOPS) and spec.get('fps')==12 and spec.get('frame_count')==count and spec.get('skin_frames')==expected and spec.get('frames')==expected['a'])

    def scope(self):
        unexpected = []
        for skin in SKINS:
            unexpected += [str(p.relative_to(self.root)) for p in (self.root/'frames'/skin).iterdir() if p.is_dir() and p.name not in ANIMS]
        self.check('only authorized swim and dash frame directories produced',not unexpected,unexpected)

    def run(self):
        self.baseline()
        self.skeleton()
        for anim,count in ANIMS.items():
            for skin in SKINS:
                self.frames(skin,anim,count)
        self.composites()
        self.sequence()
        self.renderer()
        self.manifest()
        self.scope()
        return self.report()

    def report(self):
        passed = all(item['passed'] for item in self.checks)
        return {'schema_version':3,'scope':list(ANIMS),'current_scope_passed':passed,'technical_checks_passed':passed,'render_pipeline_checks_passed':passed,'passed':passed,'checks_run':len(self.checks),'failures':[item for item in self.checks if not item['passed']],'checks':self.checks,'historical_matches':all(row['matches'] for row in self.historical_comparisons),'historical_comparisons':self.historical_comparisons,'approved_current_spec_baseline':{'files':APPROVED_SPECS,'authority':'User explicitly approved completing the revised three-stage dash in a later request.','origin_of_prior_external_edit':'unverified'},'observations':self.observations,'evidence':self.evidence,'limits':['Technical checks do not establish naturalness. Inspect actual-size PNGs/contact sheets and ask the user to review motion.','Browser file:// playback was denied earlier; do not retry or bypass it. Visual review is limited to explicitly inspected PNG frames.','Transition endpoints are checked for exact C0 pose/raster continuity with easing, not all-action C1 velocity.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    audit = Audit(root)
    try:
        report = audit.run()
    except Exception as exc:
        audit.check('validator completed',False,f'{type(exc).__name__}: {exc}')
        report = audit.report()
    path = root/'preview/qa/validation.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks_run':report['checks_run'],'failures':len(report['failures']),'report':str(path)},ensure_ascii=False))
    for failure in report['failures']:
        print('FAIL:',failure['check'])
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
