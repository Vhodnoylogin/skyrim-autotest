"""Native runtime item identities and once-only fixture creation intents."""
import copy
import re
import uuid
from .config import P

ACTION='create_fixture_runtime_potion'
REQUIREMENT='New ALCH base form with full runtime ID >=0xFF000000; a new REFR of static ALCH is insufficient'
PLACEMENT='settled reachable surface away from pouch and mouth'


def tag(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',value):
        raise ValueError('Invalid runtime item tag')


def selector(value):
    if not isinstance(value,dict) or 'runtimeItemTag' not in value:return False
    if set(value)!={'runtimeItemTag','type'} or value['type']!='ALCH':
        raise ValueError('Runtime item requires exact tag and ALCH type')
    tag(value['runtimeItemTag']);return True


def validate(operation,req):
    if req.get('action')!=ACTION:return False
    if operation!='object.perform' or set(req)!={'action','runtimeItemTag','referenceTag','templateItem',
            'quantityItems','sourceFilePolicy','creationRequirement','placement'}:
        raise ValueError('Runtime potion factory requires explicit complete contract')
    tag(req['runtimeItemTag']);tag(req['referenceTag'])
    form=req['templateItem']
    if (not isinstance(form,dict) or set(form)!={'plugin','localId','type'} or form['type']!='ALCH' or
            not isinstance(form['plugin'],str) or not re.fullmatch(r'[A-Za-z0-9 _.-]+\.(esm|esp)',form['plugin'],re.I) or
            not isinstance(form['localId'],str) or not re.fullmatch(r'[0-9a-fA-F]{1,6}',form['localId'])):
        raise ValueError('Static ALCH template plugin/local identity required')
    if (type(req['quantityItems']) is not int or req['quantityItems']!=1 or
            req['sourceFilePolicy'] not in ('absent','inherited-template-file') or
            req['creationRequirement']!=REQUIREMENT or req['placement']!=PLACEMENT):
        raise ValueError('Unsupported runtime creation/source/placement contract')
    return True


def identity(b,form,reference=False):
    if not isinstance(form,str) or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,8}',form) or int(form,16)==0:
        raise ValueError('Exact nonzero native form identity required')
    if P.value.get('native_runtime_fixtures') is not True:
        raise ValueError('Native runtime fixture provider is not configured/qualified')
    b.guard_world()
    raw=b.call('runtime_fixture',{'action':'identity','formId':form,'referenceBase':reference,
                                'timeoutMs':max(1,min(5000,int(b.remaining()*1000)))})
    item=raw.get('item',{})
    if (type(raw.get('schemaVersion')) is not int or raw['schemaVersion']!=1 or type(raw.get('pid')) is not int or raw['pid']!=b.s.state['game']['pid'] or
            raw.get('requestedFormId')!=f'0x{int(form,16):08X}' or type(raw.get('referenceBase')) is not bool or raw['referenceBase']!=reference or
            type(raw.get('frame')) is not int or raw['frame']<0 or not isinstance(item,dict) or
            not re.fullmatch(r'0x[0-9A-F]{8}',item.get('runtimeId','')) or
            type(item.get('runtimeCreated')) is not bool or not isinstance(item.get('sourceFiles'),list) or
            type(item.get('sourceFileCount')) is not int or item['sourceFileCount']!=len(item['sourceFiles']) or
            any(not isinstance(f,str) or not f for f in item['sourceFiles'])):
        raise ValueError('Native runtime form identity unavailable')
    fid=int(item['runtimeId'],16);dynamic=fid>>24==0xff;files=item['sourceFiles']
    if not reference and fid!=int(form,16):raise ValueError('Native provider returned a different base form')
    policy='absent' if not files else 'inherited-template-file' if dynamic else 'plugin-file'
    if (item['runtimeCreated']!=dynamic or item.get('sourceFilePolicy')!=policy or
            item.get('plugin')!=(files[0] if files else None) or
            (dynamic and item.get('localId') is not None)):
        raise ValueError('Inconsistent native runtime/source identity')
    b.guard_world();b.s.log('platform-native-item-identity',raw=raw,referenceBase=reference)
    return copy.deepcopy(item)


def resolve(b,spec):
    tag_name=spec['runtimeItemTag'];entry=b.s.state.get('runtimeItems',{}).get(tag_name)
    if (not entry or entry.get('status')!='completed' or entry.get('game')!=b.s.state.get('game') or
            entry.get('worldGeneration')!=b.s.state.get('ownedWorldGeneration',0)):
        raise ValueError('Runtime item tag unavailable in this exact owned world')
    observed=identity(b,entry['item']['runtimeId'])
    if observed!=entry['item'] or observed.get('formType')!='ALCH':
        raise ValueError('Runtime item identity changed; do not reuse stale tag')
    return observed['runtimeId']


def create(b,req):
    state=b.s.state;name=req['runtimeItemTag'];records=state.setdefault('runtimeItems',{})
    if name in records or name in state.get('invalidatedRuntimeItemTags',[]) or len(records)>=16:
        raise ValueError('Runtime item tag already attempted/invalidated or bound16 reached; no replay')
    # Placement is checked before allocating an engine form. A generic placement
    # provider must establish actual loaded pouch/mouth exclusion, not an alias.
    from .body_scene import plan_placement
    plan_placement(b,req['placement'])
    template=b.resolve(req['templateItem']);identity(b,template)
    owner=state.setdefault('nativeFixtureOwner',uuid.uuid4().hex);command=uuid.uuid4().hex
    entry={'status':'creating','game':copy.deepcopy(state['game']),
           'worldGeneration':state.get('ownedWorldGeneration',0),'command':command,'owner':owner,
           'request':copy.deepcopy(req)}
    records[name]=entry;b.s.save();b.s.log('platform-runtime-item-intent',tag=name,entry=entry,mutationReplayAllowed=False)
    response=b.call('runtime_fixture',{'action':'create_runtime_potion','templateFormId':template,
                    'sourceFilePolicy':req['sourceFilePolicy'],'owner':owner,'command':command,
                    'timeoutMs':max(1,min(5000,int(b.remaining()*1000)))})
    if response.get('status')!='completed' or response.get('owner')!=owner or response.get('command')!=command:
        raise ValueError('Native runtime creation receipt unavailable; do not replay')
    observed=identity(b,response.get('item',{}).get('runtimeId',''))
    if (observed!=response['item'] or observed.get('formType')!='ALCH' or observed['runtimeCreated'] is not True or
            observed['sourceFilePolicy']!=req['sourceFilePolicy'] or int(observed['runtimeId'],16)==int(template,16)):
        raise ValueError('Actual runtime ALCH identity/source differs from requested fixture')
    entry.update(status='completed',item=observed);b.s.save()
    # The reference creation remains a separate once-only ordinary engine action.
    reference=b.mutate({'action':'create_fixture_reference','item':{'runtimeItemTag':name,'type':'ALCH'},
        'referenceTag':req['referenceTag'],'quantityItems':1,'placement':req['placement']})
    b.s.log('platform-runtime-item-created',tag=name,entry=entry,reference=reference)
    return reference
