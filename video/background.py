"""Background intent is distinct from available processing; no blur masquerades as replacement."""
import re


def interpret(text,setting='auto',approved_asset=None):
    text=(text or '').casefold()
    if setting=='none' or re.search(r'(?:no change|leave|keep|do not change|don.t change).{0,25}(?:background|backdrop)|(?:background|backdrop).{0,20}(?:unchanged|as is)',text):
        intent='NO_CHANGE'
    elif setting=='replace' or re.search(r'(?:replace|swap|change).{0,30}(?:background|backdrop)|(?:background|backdrop).{0,25}(?:replace|swap|change)',text):intent='REPLACE'
    elif setting=='blur-dim' or re.search(r'blur.{0,20}(?:background|backdrop)|(?:background|backdrop).{0,20}blur',text):intent='BLUR'
    elif re.search(r'desaturat.{0,20}(?:background|backdrop)|(?:background|backdrop).{0,20}desaturat',text):intent='DESATURATE'
    elif re.search(r'(?:dim|darken).{0,20}(?:background|backdrop)|(?:background|backdrop).{0,20}(?:dim|darken)',text):intent='DIM'
    elif re.search(r'remove.{0,20}(?:distract|object)|(?:background|backdrop).{0,20}remove',text):intent='REMOVE_DISTRACTION'
    elif 'restyle' in text:intent='RESTYLE'
    elif re.search(r'background|backdrop',text):intent='CLEAN'
    else:intent='NO_CHANGE'
    mode='none' if intent=='NO_CHANGE' else 'replace' if approved_asset and intent in {'REPLACE','RESTYLE','CLEAN'} else 'blur-dim'
    params={'blur':.12,'dim':0.,'desaturate':0.}
    if intent=='DIM':params.update(blur=0.,dim=.04)
    elif intent=='DESATURATE':params.update(blur=0.,desaturate=.15)
    return dict(intent=intent,mode=mode,parameters=params,approved_asset=approved_asset,
                limitation='Local generative background reconstruction/object removal is unavailable.' if intent in {'REPLACE','REMOVE_DISTRACTION','RESTYLE','CLEAN'} and mode!='replace' else '')
