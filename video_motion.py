"""Bounded graphic entrance presets; no model output or free-form filter enters this layer."""


def preset(motion,start,end,box,width,height,intensity='minimal',already_faded=False):
    if motion=='none':return [],'0','0'
    length=min(.35,max(.08,(end-start)/3))
    step=f'min(1,max(0,(t-{start:.4f})/{length:.4f}))'
    ease=f'(1-pow(1-{step},3))'
    filters=[]
    if not already_faded:
        filters += [f'fade=t=in:st={start:.4f}:d={min(.18,length):.4f}:alpha=1',f'fade=t=out:st={max(start,end-.12):.4f}:d={min(.12,(end-start)/3):.4f}:alpha=1']
    x=y='0'
    if motion=='slide-up':
        distance=height*{'minimal':.015,'balanced':.03,'expressive':.05}[intensity]
        y=f'{distance:.4f}*(1-{ease})'
    elif motion=='masked-reveal':
        top=box[1];span=max(1,box[3]-box[1]);progress=step.replace('(t-','(T-')
        filters += [f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(Y,{top:.4f}+{span:.4f}*({progress})),alpha(X,Y),0)'",'format=rgba']
    elif motion in {'soft-scale','word-emphasis'}:
        amount=.025 if motion=='soft-scale' else .04
        factor=f'({1-amount:.5f}+{amount:.5f}*{ease})'
        filters += [f"scale=w='max(2,trunc(iw*{factor}/2)*2)':h=-2:eval=frame",'setsar=1']
        x=f'(W-w)*{(box[0]+box[2])/2/max(1,width):.5f}'
        y=f'(H-h)*{(box[1]+box[3])/2/max(1,height):.5f}'
    return filters,x,y
