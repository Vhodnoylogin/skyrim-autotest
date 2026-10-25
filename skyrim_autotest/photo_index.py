"""Derived contact sheet and factual planned-shot index; originals stay untouched."""
import hashlib
import json
import math
import struct
import zlib

from .assisted_capture import image_info


def thumbnail(data,width=240,height=135):
    info=image_info(data)
    if info['format']!='png':raise ValueError('Contact sheet requires verified PNG')
    offset=8;compressed=bytearray();colour=None
    while offset<len(data):
        size=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8];payload=data[offset+8:offset+8+size]
        if kind==b'IHDR':colour=payload[9]
        if kind==b'IDAT':compressed.extend(payload)
        offset+=size+12
    channels={0:1,2:3,4:2,6:4}[colour];w,h=info['width'],info['height'];stride=w*channels
    pixels=zlib.decompress(compressed)  # Already checked against bounded complete stream above.
    previous=bytearray(stride);out=bytearray([32]*(width*height*3))
    scale=min(width/w,height/h);draw_w=max(1,min(width,round(w*scale)));draw_h=max(1,min(height,round(h*scale)))
    x_offset=(width-draw_w)//2;y_offset=(height-draw_h)//2
    selected={}
    for y in range(draw_h):selected.setdefault(min(h-1,y*h//draw_h),[]).append(y+y_offset)
    for y in range(h):
        start=y*(stride+1);kind=pixels[start];row=bytearray(pixels[start+1:start+1+stride])
        if kind:
            for x in range(stride):
                left=row[x-channels] if x>=channels else 0;up=previous[x];corner=previous[x-channels] if x>=channels else 0
                if kind==1:predict=left
                elif kind==2:predict=up
                elif kind==3:predict=(left+up)//2
                else:
                    estimate=left+up-corner;a,b,c=abs(estimate-left),abs(estimate-up),abs(estimate-corner)
                    predict=left if a<=b and a<=c else up if b<=c else corner
                row[x]=(row[x]+predict)&255
        for dy in selected.get(y,[]):
            for dx in range(draw_w):
                x=min(w-1,dx*w//draw_w)*channels
                rgb=row[x:x+3] if colour in (2,6) else bytes([row[x]])*3
                out[(dy*width+dx+x_offset)*3:(dy*width+dx+x_offset+1)*3]=rgb
        previous=row
    return out


def png(width,height,pixels):
    def chunk(key,data):return struct.pack('>I',len(data))+key+data+struct.pack('>I',zlib.crc32(key+data)&0xffffffff)
    stride=width*3;rows=b''.join(b'\0'+pixels[y*stride:(y+1)*stride] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+
            chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))


def write(session):
    from .runner import atomic_json,sha
    from .photography import name
    s=session.state['photography'];planned=[];group=None;scenario=session.dir/'scenario.json'
    if scenario.is_file():
        expected=session.state.get('scenarioHash')
        if expected and sha(scenario)!=expected:raise ValueError('Frozen scenario changed before photography indexing')
        for step in json.loads(scenario.read_text(encoding='utf-8-sig')).get('steps',[]):
            args=step.get('args',{});request=args.get('request',{})
            if step.get('tool')!='platform':continue
            if request.get('action')=='frame_fixture_actor':group=request['framing']['comparisonGroup']
            if request.get('action')=='capture_fixture_photo':planned.append({'id':name(request['photoId']),'group':group})
    if not planned:planned=[{'id':name(k),'group':v.get('group')} for k,v in s['photos'].items()]
    if len(planned)>32 or len({v['id'] for v in planned})!=len(planned):raise ValueError('Photo index exceeds bound or duplicate planned IDs')
    # Adjacent cells represent members of the same requested comparison group.
    ordinal={v['id']:i for i,v in enumerate(planned)}
    planned.sort(key=lambda v:(v['group'] or '',ordinal[v['id']]))
    records=[];pairs={};tile_w,tile_h=240,135;cols=4;rows=max(1,math.ceil(len(planned)/cols))
    pixels=bytearray([32]*(cols*tile_w*rows*tile_h*3))
    for i,item in enumerate(planned):
        record=s['photos'].get(item['id'],{});row={**item,'cell':i+1,'status':record.get('status','not_run')}
        if record.get('status')=='verified':
            from pathlib import Path
            data=Path(record['image']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('Original photo changed before index')
            thumb=thumbnail(data);x=(i%cols)*tile_w;y=(i//cols)*tile_h
            for dy in range(tile_h):
                dest=((y+dy)*cols*tile_w+x)*3
                pixels[dest:dest+tile_w*3]=thumb[dy*tile_w*3:(dy+1)*tile_w*3]
            row.update(original=record['image'],sha256=record['sha256'],configuration={'key':record['morphKey'],'values':record['morphs']})
        records.append(row);pairs.setdefault(item['group'],[]).append(item['id'])
    index={'schemaVersion':1,'runId':session.state['id'],'shots':records,'groups':pairs,
           'pairs':[{'group':g,'members':ids} for g,ids in pairs.items() if g is not None and len(ids)==2],
           'contactSheet':{'file':'photography-contact-sheet.png','derivedPreview':True,'columns':cols,
                           'cellWidth':tile_w,'cellHeight':tile_h,'blankCellMeaning':'missing/unverified; consult shots status'}}
    contact=session.dir/'photography-contact-sheet.png';contact.write_bytes(png(cols*tile_w,rows*tile_h,pixels))
    index['contactSheet']['sha256']=sha(contact);atomic_json(session.dir/'photography-index.json',index)
    return index
