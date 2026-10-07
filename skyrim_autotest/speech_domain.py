"""Candidate native Speech Broker observations. Never inject text or bids."""
import copy
import hashlib
import math
import re
from .config import P

OBSERVATIONS = {'speech.broker.status', 'speech.subscribers', 'speech.vocabulary',
                'speech.utterances', 'speech.door_recognition', 'speech.door_awards', 'speech.event_roundtrip'}
ACTION = 'speech.event_roundtrip.request'


def validate(operation, req):
    selector = req.get('observation', req.get('action'))
    if selector not in OBSERVATIONS | {ACTION}: return False
    if operation != ('object.perform' if selector == ACTION else 'world.read'):
        raise ValueError('Wrong operation for speech selector')
    expected = {'observation'}
    if selector == 'speech.vocabulary': expected |= {'key'}
    if selector in ('speech.utterances', 'speech.door_recognition', 'speech.door_awards'): expected |= {'idRange'}
    if selector in ('speech.door_recognition', 'speech.door_awards'): expected |= {'namespace', 'minimumVocabularyScoreExclusive'}
    if selector == ACTION: expected = {'action', 'count', 'target'}
    optional = {'subscriberNamespaces'} if selector == 'speech.utterances' else set()
    if not expected <= set(req) or set(req)-expected-optional: raise ValueError('Unsupported/missing speech fields')
    if 'subscriberNamespaces' in req:
        names=req['subscriberNamespaces']
        if not isinstance(names,list) or not 1<=len(names)<=3 or len(set(names))!=len(names):
            raise ValueError('One to three unique subscriber namespaces required')
        for name in names:text(name,96,pattern=r'[A-Za-z0-9 _.-]+')
    if 'idRange' in req:
        scope = req['idRange']
        if (not isinstance(scope, dict) or set(scope) != {'first', 'last'} or
                any(type(scope[k]) is not int for k in scope) or
                not 1 <= scope['first'] <= scope['last'] <= 100000 or scope['last'] - scope['first'] >= 16):
            raise ValueError('Speech ID range requires at most16 explicit positive IDs')
    if 'namespace' in req: text(req['namespace'], 96, pattern=r'[A-Za-z0-9 _.-]+')
    if 'key' in req: text(req['key'], 128, pattern=r'\$[A-Z0-9_]+')
    if 'minimumVocabularyScoreExclusive' in req: number(req['minimumVocabularyScoreExclusive'], 0, 1)
    if selector == ACTION and (type(req['count']) is not int or req['count'] != 1 or req['target'] != 'speech-broker'):
        raise ValueError('Only one ordinary broker roundtrip request supported')
    return True


def text(value, limit=16384, pattern=None):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or (pattern and not re.fullmatch(pattern, value)):
        raise ValueError('Native speech text unavailable or invalid')
    return value


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Native speech number unavailable or invalid')
    return value


def strings(value):
    if not isinstance(value, list) or len(value) > 256: raise ValueError('Native speech string array unavailable')
    return [text(s, 1024) for s in value]


def native(b, fn, args=None): return b.pap('SpeechBroker', fn, args)


def reads(b, calls):
    return b.pap_read_batch([{'script':'SpeechBroker','function':fn,'args':args} for fn,args in calls])


def log_file(): return P.skse_logs / 'SpeechBroker.log'


def log_bytes():
    path = log_file()
    if not path.is_file() or path.stat().st_size > 4*1024*1024:
        raise ValueError('Bounded current Speech Broker log unavailable')
    data = path.read_bytes()
    if len(data) > 4*1024*1024: raise ValueError('Speech log grew beyond bound')
    return data


def template_pattern(value):
    text(value, 2048)
    if '{0}' not in value or value.startswith('$'): raise ValueError('Localized selftest template unavailable')
    # Match only an entire provider log message, never substrings of utterance text.
    chunks = re.split(r'(\{[01]\})', value); result = ''
    for chunk in chunks:
        if chunk == '{0}': result += r'(?P<token>[1-9][0-9]*)'
        elif chunk == '{1}': result += r'(?P<milliseconds>[0-9]+)'
        else: result += re.escape(chunk)
    return re.compile(r'^\[[0-9:. -]+\] \[global log\] \[(?:info|debug)\] '+result+r'\r?$', re.MULTILINE)


def appended(state):
    data = log_bytes(); offset = state['offset']
    if len(data) < offset or hashlib.sha256(data[:offset]).hexdigest() != state['prefixSha256']:
        raise ValueError('Speech roundtrip log rotated/truncated/replaced')
    return data[offset:].decode('utf-8', errors='strict')


def perform(b, req):
    if b.s.state.get('speechRoundtrip'): raise ValueError('Speech roundtrip already requested; never replay')
    start = native(b, 'Translate', ['$SPEECHBROKER_LOG_SELFTEST_START'])
    ok = native(b, 'Translate', ['$SPEECHBROKER_LOG_SELFTEST_OK'])
    start_pattern = template_pattern(start); template_pattern(ok)
    baseline = log_bytes()
    if baseline and not baseline.endswith(b'\n'): raise ValueError('Speech log baseline ends in partial record')
    state = {'game': copy.deepcopy(b.s.state.get('game')), 'offset': len(baseline),
             'prefixSha256': hashlib.sha256(baseline).hexdigest(), 'startTemplate': start, 'okTemplate': ok,
             'status': 'requesting', 'token': None}
    if not state['game']: raise ValueError('Owned speech game identity unavailable')
    b.s.state['speechRoundtrip'] = state; b.s.save()
    b.s.log('platform-speech-roundtrip-intent', state=state, mutationReplayAllowed=False)
    native(b, 'SelfTest')
    tail = appended(state); tokens = [int(m['token']) for m in start_pattern.finditer(tail)]
    if len(tokens) != 1: raise ValueError('Exactly one correlated new selftest start token required')
    state.update(token=tokens[0], status='waiting'); b.s.save()
    b.s.log('platform-speech-roundtrip-requested', token=state['token'], appendedLog=tail, completionProven=False)
    return {'speech': {'events': {'roundtripRequested': True, 'token': state['token']}}}


def roundtrip(b):
    state = b.s.state.get('speechRoundtrip', {})
    if state.get('status') not in ('waiting', 'completed') or state.get('game') != b.s.state.get('game'):
        raise ValueError('Current requested speech roundtrip identity unavailable')
    tail = appended(state); starts = [int(m['token']) for m in template_pattern(state['startTemplate']).finditer(tail)]
    if starts != [state['token']]: raise ValueError('Overlapping speech selftest tokens; correlation unavailable')
    matches = [m for m in template_pattern(state['okTemplate']).finditer(tail) if int(m['token']) == state['token']]
    completed = bool(matches)
    if completed: state['status'] = 'completed'; b.s.save()
    b.s.log('platform-speech-roundtrip-observation', token=state['token'], completed=completed, appendedLog=tail)
    return {'speech': {'events': {'roundtripCompleted': completed, 'token': state['token'],
                                 'evidenceStatus': 'completed' if completed else 'pending'}}}


def observe(b, req):
    kind = req['observation']
    if kind == 'speech.event_roundtrip': return roundtrip(b)
    if kind == 'speech.broker.status':
        available, version, adapters, source = reads(b,[('IsAvailable',[]),('GetInterfaceVersion',[]),
                                                      ('GetAdapters',[]),('GetSource',['asr'])])
        if type(available) is not bool or type(version) is not int or version <= 0:
            raise ValueError('Native broker availability/version unavailable')
        return {'speech': {'broker': {'available': available, 'interfaceVersion': version,
                'adapters': strings(adapters), 'asrSource': text(source, 1024)}}}
    if kind == 'speech.subscribers': return {'speech': {'subscribers': {'namespaces': strings(native(b, 'GetNamespaces'))}}}
    if kind == 'speech.vocabulary': return {'speech': {'vocabulary': {'phrase': text(native(b, 'Translate', [req['key']]))}}}
    records = []; count = 0
    ids=list(range(req['idRange']['first'], req['idRange']['last']+1))
    texts=reads(b,[('GetText',[ident]) for ident in ids])
    for ident, observed_text in zip(ids,texts):
        utterance = text(observed_text)
        if not utterance: continue  # Broker's documented absence result, not a fabricated utterance.
        if kind == 'speech.utterances':
            row = {'id': ident, 'text': utterance}
            names=req.get('subscriberNamespaces',['DemoGreedy','DemoShared'])
            functions=['GetTopic','GetOutcome','GetWinner','GetEngineId','GetLatencyMs','GetScore','GetComplete','IsFinal']
            calls=[(fn,[ident]) for fn in functions]
            for namespace in names:calls.extend([('GetVocabularyScore',[ident,namespace]),('GetDenyReason',[ident,namespace])])
            # Re-read text to detect eviction/replacement during these non-atomic reads.
            calls.append(('GetText',[ident]))
            values=reads(b,calls)
            if text(values[-1])!=utterance:raise ValueError('Native utterance changed during observation')
            for name, value in zip(('topic','outcome','winner','engineId'),values[:4]):row[name]=text(value)
            latency = values[4]
            if type(latency) is not int or latency < 0: raise ValueError('Native latency milliseconds unavailable')
            row['latencyMs'] = latency
            for name, value in zip(('score','complete'),values[5:7]): row[name] = number(value, 0, 1)
            row['isFinal'] = values[7]
            if type(row['isFinal']) is not bool: raise ValueError('Native utterance final flag unavailable')
            row['subscribers']={namespace:{'vocabularyScore':number(values[8+2*i],0,1),
                                           'denial':text(values[9+2*i])} for i,namespace in enumerate(names)}
            if 'subscriberNamespaces' not in req:
                row['greedyVocabulary']=row['subscribers']['DemoGreedy']['vocabularyScore']
                row['greedyDenial']=row['subscribers']['DemoGreedy']['denial']
                row['sharedDenial']=row['subscribers']['DemoShared']['denial']
            records.append(row)
        else:
            calls=[('GetVocabularyScore',[ident,req['namespace']])]
            if kind == 'speech.door_awards':calls.append(('IsWinner',[ident,req['namespace']]))
            calls.append(('GetText',[ident]))
            values=reads(b,calls)
            if text(values[-1])!=utterance:raise ValueError('Native utterance changed during observation')
            score = number(values[0], 0, 1)
            matched = score > req['minimumVocabularyScoreExclusive']
            row = {'id': ident, 'text': utterance, 'vocabularyScore': score}
            if kind == 'speech.door_awards':
                winner = values[1]
                if type(winner) is not bool: raise ValueError('Native winner flag unavailable')
                matched &= winner; row['isWinner'] = winner
            count += int(matched); records.append(row)
    b.s.log('platform-speech-native-records', observation=kind, records=records, atomicSnapshot=False,
            noTextInjection=True, noBidsSubmitted=True)
    if kind == 'speech.utterances': return {'speech': {'utterances': {'records': records}}}
    return {'speech': {('recognition' if kind == 'speech.door_recognition' else 'auction'):
                      {('doorTextCount' if kind == 'speech.door_recognition' else 'doorGreedyAwardCount'): count}},
            'providerRecords': records}
