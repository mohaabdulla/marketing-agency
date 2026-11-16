"""Joint, time-aware graphic composition over measured boxes and platform exclusions.

The beam search scores complete arrangements; a caption cannot independently claim a CTA's
space. Face/head are protected, body/matte coverage and saliency are soft costs. Unavailable
hand/object/text detection is explicitly unmeasured, not fabricated as empty detections.
"""
import math
from pydantic import Field
from video_projects import Strict
from video_captions import CaptionStyle, track_style
from video_typography import compose
from video_platforms import safe_area


class LayoutElement(Strict):
    id: str
    role: str
    start: float
    end: float
    box: list[float] = Field(min_length=4,max_length=4)
    score: float
    evidence: dict
    requires_review: bool
    font_size_px: int | None = None
    priority: int


def intersection(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def area(box):
    return max(1,(box[2]-box[0])*(box[3]-box[1]))


def active(a,b):
    return min(a['end'],b['end'])>max(a['start'],b['start'])+.01


def analyze_frame(frame,face=None,matte=None,extra_regions=()):
    import cv2
    import numpy as np
    if frame is None:
        regions=list(extra_regions)
        if face:
            x,y,fw,fh=[face[k] for k in ('x','y','width','height')]
            regions.append(dict(kind='face',box=[x,y,x+fw,y+fh],basis='SUPPLIED_MEASURED_FACE'))
        return dict(face=face,regions=regions,not_measured=['saliency','local contrast','hands','objects','existing text'])
    h,w=frame.shape[:2]
    small=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(96,96)).astype('float32')/255
    energy=cv2.magnitude(cv2.Sobel(small,cv2.CV_32F,1,0),cv2.Sobel(small,cv2.CV_32F,0,1))
    energy=np.minimum(1,energy/max(.05,float(np.percentile(energy,95))))
    regions=list(extra_regions)
    if face:
        x,y,fw,fh=[face[k] for k in ('x','y','width','height')]
        regions += [dict(kind='face',box=[x,y,x+fw,y+fh],basis='MEASURED_FACE'),
                    dict(kind='head',box=[max(0,x-.12*fw),max(0,y-.35*fh),min(1,x+1.12*fw),min(1,y+1.1*fh)],basis='CONSERVATIVE_FACE_EXPANSION')]
        if matte is None:
            regions.append(dict(kind='body',box=[max(0,x-fw),min(1,y+fh),min(1,x+fw*2),1.],basis='ESTIMATED_FROM_FACE'))
    if matte is not None:
        binary=matte>127
        ys,xs=np.nonzero(binary)
        if len(xs):regions.append(dict(kind='body',box=[float(xs.min()/matte.shape[1]),float(ys.min()/matte.shape[0]),float((xs.max()+1)/matte.shape[1]),float((ys.max()+1)/matte.shape[0])],basis='MEASURED_MATTE_BOUNDS'))
    return dict(face=face,regions=regions,source_size=[w,h],saliency=energy.round(3).tolist(),luminance=small.round(3).tolist(),
                not_measured=['hand identity/gesture regions','object semantics','existing text/OCR'],
                notice='Saliency is gradient energy, not semantic importance. Body estimates are labelled separately from measured matte bounds.')


def design_tokens(rules, width, language, height=None):
    from video_captions import brand_caption_style
    base,notices=brand_caption_style(rules,language)
    # Actual frame pixels define hierarchy; legacy 1280-based sizes remain readable fallbacks.
    # Type scales with the shorter reading dimension: sized from the width alone, a 16:9 frame
    # got titles nearly twice as large as the same design in 9:16.
    reference=width
    if height:width=min(width,round(height*.9))
    sizes={'DIALOGUE_CAPTION':max(18,round(width*.047)), 'LOWER_THIRD':max(18,round(width*.041)),
           'CTA':max(24,round(width*.055)), 'TITLE':max(24,round(width*.058)),
           'HOOK':max(26,round(width*.063)), 'DISCLOSURE':max(16,round(width*.035)), 'LABEL':max(18,round(width*.04))}
    if rules.caption_size:
        sizes['DIALOGUE_CAPTION']=max(18,round(rules.caption_size*width/1280))
    plate=(rules.primary_colors[0] if rules.primary_colors else '#07111c')+'e8'
    roles={}
    for role,size in sizes.items():
        minimum=24 if role in {'CTA','TITLE','HOOK'} else min(size,18)
        roles[role]=dict(base,font_size_px=min(96,size),reference_width=reference,min_font_px=minimum,max_lines=2,
                         font_weight='bold' if role in {'CTA','HOOK','TITLE'} else 'regular' if role=='DISCLOSURE' else 'bold',
                         background=plate if role in {'CTA','LOWER_THIRD','TITLE','HOOK'} else '#07111cc9',
                         padding=8 if role in {'CTA','LOWER_THIRD'} else 6,stroke_width=1,tracking=.2 if role=='CTA' and not language.startswith('ar') else 0.,
                         line_height=1.22,max_width_pct=.68 if role!='LOWER_THIRD' else .59)
    return dict(version=1,logo=dict(clear_space=rules.logo_clear_space,placement=rules.logo_placement),typography=roles,
                colors=rules.primary_colors+rules.secondary_colors,motion=rules.animation_style,
                prohibited=rules.prohibited_elements,notices=notices)


def readable_plate(style,palette):
    """Keep the requested ink color; choose a contrasting approved plate first.
    Neutral black/white are fallback backing treatments, never invented brand copy.
    """
    from video_measure import contrast_ratio
    from creative.colors import parse_color
    ink=parse_color(style.fill)[:3]
    colors=list(dict.fromkeys(palette+['#07111c','#ffffff']))
    selected=next((c for c in colors if contrast_ratio(ink,parse_color(c)[:3])>=7),None)
    if selected is None:selected=max(colors,key=lambda c:contrast_ratio(ink,parse_color(c)[:3]))
    dark=sum(ink)<300
    return style.model_copy(update={'background':selected+'f0','stroke':None if dark else '#000000','stroke_width':0 if dark else 1})


def solve(project,platform,face=None,scene=None,rules=None):
    from video_brand_editing import effective_rules
    from video_assets import read
    w,h=project.canvas.width,project.canvas.height
    rules=rules or effective_rules(project)
    scene=scene or analyze_frame(None,face)
    tokens=design_tokens(rules,w,project.creative_context.language,h)
    bounds=safe_area(platform,w,h)
    left,top,right,bottom=bounds
    gap=max(6,w*.018)
    items=[]
    for clip in project.clips:
        if clip.kind=='overlay':
            meta=read('assets',clip.asset_id)
            clip.scale=min(clip.scale,.23)
            lw=round(w*clip.scale/2)*2
            pad=max(8,round(meta['width']*.05)) if clip.logo_backplate else 0
            lh=round(lw*(meta['height']+2*pad)/(meta['width']+2*pad))
            items.append(dict(id=clip.id,role='LOGO',start=clip.start,end=clip.start+clip.duration,width=lw,height=lh,clip=clip,priority=0))
        elif clip.kind=='title':
            role={'cta':'CTA','hook':'HOOK','disclosure':'DISCLOSURE','lower_third':'LOWER_THIRD'}.get(clip.text_role,'TITLE')
            style=CaptionStyle.model_validate(tokens['typography'][role])
            style.fill=clip.color
            style=readable_plate(style,tokens['colors'])
            items.append(dict(id=clip.id,role=role,start=clip.start,end=clip.start+clip.duration,text=clip.text,style=style,clip=clip,priority=1 if role=='CTA' else 2))
    for track in project.caption_tracks:
        role='LOWER_THIRD' if track.get('kind')=='lower-third' else 'DIALOGUE_CAPTION'
        base=CaptionStyle.model_validate(tokens['typography'][role])
        # Respect explicit track brand snapshots while applying the role hierarchy.
        old=track_style(track)
        base=base.model_copy(update={'fill':old.fill,'font_name':old.font_name})
        base=readable_plate(base,tokens['colors'])
        for index,seg in enumerate(track.get('segments',[])):
            items.append(dict(id=track['id']+f'-{index}',role=role,start=seg['start'],end=seg['end'],text=seg['text'],style=base,segment=seg,track=track,priority=2 if role=='LOWER_THIRD' else 3))
    # Fixed creative graphics reserve space first; sequential caption cues then share a stable zone.
    items.sort(key=lambda x:(x['priority'],x['start'],x['id']))
    sw,sh=scene.get('source_size',[w,h]);factor=max(w/sw,h/sh)
    scaled_w,scaled_h=sw*factor,sh*factor
    def projected(region):
        box=region['box']
        ax=(box[0]+box[2])/2 if region['kind']=='face' else face['x']+face['width']/2 if face else .5
        ay=(box[1]+box[3])/2 if region['kind']=='face' else face['y']+face['height']/2 if face else .5
        ox=max(0,min(scaled_w-w,scaled_w*ax-w/2));oy=max(0,min(scaled_h-h,scaled_h*ay-h/2))
        return [max(0,box[0]*scaled_w-ox),max(0,box[1]*scaled_h-oy),min(w,box[2]*scaled_w-ox),min(h,box[3]*scaled_h-oy)]
    protected=[dict(r,box=projected(r)) for r in scene.get('regions',[])]
    if scene.get('saliency') and abs(sw/sh-w/h)>.01:
        import cv2
        import numpy as np
        ax=face['x']+face['width']/2 if face else .5;ay=face['y']+face['height']/2 if face else .5
        ox=max(0,min(scaled_w-w,scaled_w*ax-w/2))/scaled_w;oy=max(0,min(scaled_h-h,scaled_h*ay-h/2))/scaled_h
        grid=np.array(scene['saliency'],dtype='float32');crop=grid[int(oy*96):max(int(oy*96)+1,int((oy+h/scaled_h)*96)),int(ox*96):max(int(ox*96)+1,int((ox+w/scaled_w)*96))]
        scene=dict(scene,saliency=cv2.resize(crop,(96,96)).tolist())
    def candidates(item):
        if item['role']=='LOGO':
            lw,lh=item['width'],item['height']
            return [(dict(box=[x,y,x+lw,y+lh]),None) for x in (right-lw-gap,left+gap) for y in (top+gap,bottom-lh-gap)]
        style=item['style']
        safe_width=(right-left-2*gap)/w
        style=style.model_copy(update={'max_width_pct':min(style.max_width_pct,max(.3,safe_width))})
        rows=[.72,.64,.30,.23,.80,.56,.40]
        columns=[(left+right)/2/w, max(.2,min(.8,(left+(right-left)*.4)/w)),max(.2,min(.8,(left+(right-left)*.6)/w))]
        result=[]
        for y in rows:
            for x in columns:
                candidate=style.model_copy(update={'x_center_pct':x,'y_pct':y})
                info,*_=compose(item['text'],w,h,candidate)
                # Clamp a measured rectangle, not a guessed percentage, into the safe region.
                box=info['box'];dx=max(0,left+gap-box[0])-max(0,box[2]-(right-gap));dy=max(0,top+gap-box[1])-max(0,box[3]-(bottom-gap))
                if dx or dy:
                    candidate=candidate.model_copy(update={'x_center_pct':max(.2,min(.8,x+dx/w)),'y_pct':max(.1,min(.95,y+dy/h))})
                    info,*_=compose(item['text'],w,h,candidate)
                result.append((info,candidate))
        return result
    def score(item,info,chosen):
        box=info['box'];size=area(box)
        unsafe=1-intersection(box,bounds)/size
        face_share=hands=body=0.
        for region in protected:
            rb=region['box']
            if region['kind'] in {'face','head'}:
                # Clearance, not mere non-overlap: a plate touching the hair or chin reads as a collision.
                rb=[rb[0]-gap,rb[1]-2*gap,rb[2]+gap,rb[3]+2*gap]
            share=intersection(box,rb)/size
            if region['kind'] in {'face','head'}:face_share=max(face_share,share)
            elif region['kind']=='hand':hands=max(hands,share)
            elif region['kind']=='body':body=max(body,share)
        collision=0.
        for other in chosen:
            if active(item,other):
                expanded=[other['box'][0]-gap,other['box'][1]-gap,other['box'][2]+gap,other['box'][3]+gap]
                collision+=intersection(box,expanded)/size
        baseline={'LOGO':.16,'LOWER_THIRD':.30,'CTA':.72,'DIALOGUE_CAPTION':.72,'HOOK':.25,'TITLE':.30,'DISCLOSURE':.80}.get(item['role'],.72)
        preference=abs((box[1]+box[3])/2/h-baseline)*25
        if item['role']=='DIALOGUE_CAPTION':
            previous=next((c for c in reversed(chosen) if c['role']=='DIALOGUE_CAPTION'),None)
            if previous:preference+=abs((box[1]+box[3]-previous['box'][1]-previous['box'][3])/2/h)*35
        saliency=0.
        if scene.get('saliency'):
            grid=scene['saliency'];values=[row[max(0,int(box[0]/w*96)):min(96,int(math.ceil(box[2]/w*96)))] for row in grid[max(0,int(box[1]/h*96)):min(96,int(math.ceil(box[3]/h*96)))]]
            flat=[v for row in values for v in row];saliency=sum(flat)/len(flat) if flat else 0.
        cost=unsafe*4000+face_share*3000+hands*1000+collision*5000+body*(65 if item['role']=='LOWER_THIRD' else 5)+saliency*3+preference
        if info.get('exceeds_lines') or info.get('oversized_word'):cost+=1000
        return cost,dict(face_overlap=round(face_share,4),hand_overlap=round(hands,4),body_overlap=round(body,4),graphic_overlap=round(collision,4),unsafe_share=round(unsafe,4),saliency=round(saliency,4))
    beam=[(0.,[])]
    for item in items:
        choices=candidates(item)
        expanded=[]
        for total,chosen in beam:
            for info,style in choices:
                cost,evidence=score(item,info,chosen)
                element=dict(id=item['id'],role=item['role'],start=item['start'],end=item['end'],box=info['box'],score=round(cost,3),evidence=evidence,
                             requires_review=bool(evidence['face_overlap']>.01 or evidence['graphic_overlap']>.01 or evidence['unsafe_share']>.01 or info.get('exceeds_lines') or info.get('oversized_word')),
                             font_size_px=info.get('font_size'),priority=item['priority'],style=style.model_dump() if style else None)
                expanded.append((total+cost,chosen+[element]))
        beam=sorted(expanded,key=lambda x:x[0])[:6]
    chosen=beam[0][1] if beam else []
    by_id={e['id']:e for e in chosen}
    for item in items:
        selected=by_id[item['id']]
        if item.get('segment') is not None:
            item['segment']['layout_style']=selected['style']
            item['segment']['layout_box']=selected['box']
            item['segment']['layout_track_origin']={k:item['track'].get(k) for k in ('y_pct','x_center_pct','max_width_pct') if item['track'].get(k) is not None}
        else:
            clip=item['clip'];clip.layout_box=selected['box']
            if item['role']=='LOGO':
                bw,bh=selected['box'][2]-selected['box'][0],selected['box'][3]-selected['box'][1]
                clip.x=max(0,min(1,selected['box'][0]/max(1,w-bw)));clip.y=max(0,min(1,selected['box'][1]/max(1,h-bh)))
            else:
                clip.graphic_style=dict(selected['style'],canvas_height=h,canvas_width=w);clip.scale=1.
    elements=[LayoutElement.model_validate({k:v for k,v in e.items() if k!='style'}).model_dump() for e in chosen]
    return dict(version=1,canvas=[w,h],elements=elements,zones=dict(platform_safe=list(bounds),protected=protected),design_tokens=tokens,
                score=round(beam[0][0],3) if beam else 0.,score_meaning='Internal arrangement cost, not a creative quality score',
                not_measured=scene.get('not_measured',[]),method='Joint temporal beam search over real text/plate boxes; face, graphics and platform exclusions dominate the cost')
