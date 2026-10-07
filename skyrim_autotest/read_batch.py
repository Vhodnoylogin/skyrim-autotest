"""Bounded parallel native getters, with one owned-process identity bracket.

This is not an atomic world snapshot. No setters, arbitrary tools, retries,
fallback requests or queued mutations are admitted.
"""
import concurrent.futures
import copy
import threading
import time
from . import native, runner

GETTERS = {
    'SpeechBroker': frozenset(('IsAvailable GetInterfaceVersion GetAdapters GetSource '
        'GetNamespaces Translate GetText GetTopic GetOutcome GetWinner GetEngineId '
        'GetLatencyMs GetScore GetComplete IsFinal GetVocabularyScore GetDenyReason IsWinner').split()),
    'ObjectReference': frozenset(('GetPositionX GetPositionY GetPositionZ').split()),
    'NetImmerse': frozenset(('GetNodeWorldPositionX GetNodeWorldPositionY GetNodeWorldPositionZ').split()),
    'VRIK': frozenset(('VrikGetSlot',)),
}


def execute(session, calls, deadline):
    if not isinstance(calls, list) or not 1 <= len(calls) <= 16:
        raise ValueError('Read batch requires1..16 explicit getters')
    calls=copy.deepcopy(calls)
    for call in calls:
        if (not isinstance(call,dict) or set(call)-{'script','function','args','self'} or
                call.get('function') not in GETTERS.get(call.get('script'), ()) or
                not isinstance(call.get('args',[]),list)):
            raise ValueError('Read batch only accepts allowlisted native getters')
    game=copy.deepcopy(session.state['game']);port=session.state['port']
    stop=threading.Event();started=time.monotonic()

    def remaining(limit):
        value=deadline-time.monotonic()
        if value<=0 or stop.is_set():raise TimeoutError('Read batch deadline exhausted or batch aborted')
        return min(limit,value)

    def identity():
        health=runner.request(port,'api/health',timeout=remaining(3))
        if health.get('pid')!=game['pid'] or not native.alive(game) or session.state['game']!=game:
            raise runner.Blocked('Read batch game identity changed')

    def read(index):
        args={'action':'call',**calls[index],'timeoutMs':max(1,int(remaining(6)*1000))}
        if not native.alive(game):raise runner.Blocked('Read batch owned game exited')
        begin=time.monotonic()
        result=runner.request(port,'api/tool/papyrus',args,timeout=remaining(12))
        session.log('native-read-batch-item',index=index,args=args,result=result,
                    elapsedMs=int((time.monotonic()-begin)*1000),game=game)
        if (not isinstance(result,dict) or result.get('isError') or result.get('error') or
                'returned' not in result):raise ValueError('Native read batch getter failed or return value unavailable')
        remaining(12)
        return result['returned']

    identity();results=[None]*len(calls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4,len(calls))) as pool:
        pending={pool.submit(read,i):i for i in range(len(calls))}
        try:
            for future in concurrent.futures.as_completed(pending,timeout=remaining(float('inf'))):
                results[pending[future]]=future.result()
        except BaseException:
            stop.set()
            for future in pending:future.cancel()
            raise
    identity()
    session.log('native-read-batch',calls=calls,game=game,atomicSnapshot=False,
                elapsedMs=int((time.monotonic()-started)*1000),workers=min(4,len(calls)),
                identityBracketVerified=True,results=results)
    return results
