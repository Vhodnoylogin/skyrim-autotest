"""Startup-only reads abandoned before execution may wait within one deadline."""
import json
import re
import time


_FROZEN_STARTUP_ABANDONED = (
    'main-thread task did not start within 5000ms; queued task abandoned and the game frame counter '
    'has not advanced -- main thread hung or the game is fully paused; if no pause menu is open, '
    'only a process restart recovers')
_MAIN_MENU_CONTEXT = (' [blocked by Main Menu: the game is at the main menu; '
                      'load a save with game action=load or loadLast]')


def _abandoned_timeout(body, startup_snapshot, main_menu_read):
    if not isinstance(body, dict) or body.get('code') != 504 or not isinstance(body.get('error'), str):
        return False
    message = body['error']
    if main_menu_read:
        message = message.removesuffix(_MAIN_MENU_CONTEXT)
    return (re.fullmatch(r'main-thread task did not start within [0-9]+ms; queued task abandoned'
                         r'(?: \([0-9]+ frames elapsed -- main thread busy\))?', message) is not None
            or (startup_snapshot and message == _FROZEN_STARTUP_ABANDONED))


class ReadinessSession:
    def __init__(self, session, deadline):
        self.session, self.deadline = session, deadline

    def __getattr__(self, name): return getattr(self.session, name)

    def tool(self, name, args, timeout=12, deadline=None):
        from .runner import HTTPResponseError, ToolError
        end = min(self.deadline, deadline) if deadline is not None else self.deadline
        startup_snapshot = name == 'menu' and args == {'action':'startup', 'startupOperation':'snapshot'}
        main_menu_read = name == 'gfx' and args.get('op') == 'get' and args.get('menu') == 'Main Menu'
        readonly = ((name == 'inspect' and args in ({'kind':'state'}, {'kind':'scene'})) or
                    startup_snapshot or
                    (name == 'gfx' and args.get('op') == 'get') or
                    (name == 'menu' and args.get('action') in ('list','describe')) or
                    (name == 'papyrus' and args.get('action') == 'describe'))
        attempt = 0
        while True:
            remaining = end-time.monotonic()
            if remaining <= 0: raise TimeoutError('Common readiness read deadline exhausted: '+name)
            attempt += 1
            try:
                result = self.session.tool(name,args,timeout=min(timeout,remaining),deadline=end)
            except (HTTPResponseError,ToolError) as error:
                abandoned = False
                if readonly and isinstance(error,ToolError):
                    abandoned = (error.tool == name and error.args_value == args and
                                 error.result.get('ok') is False and
                                 error.result.get('outcome') == 'abandoned_before_start')
                elif readonly and error.status == 504 and error.route == 'api/tool/'+name:
                    try: body = json.loads(error.body)
                    except (ValueError,TypeError): body = {}
                    # Exact pinned DevBench MainThread pre-execution timeout,
                    # not an arbitrary HTTP504, started task or transport loss.
                    # A frozen frame sample is not permanent-hang proof. Only
                    # this exact startup snapshot may retry that pinned variant.
                    abandoned = _abandoned_timeout(body, startup_snapshot, main_menu_read)
                if not abandoned: raise
                self.session.log('common-readiness-abandoned-read',tool=name,args=args,attempt=attempt,
                                 error=str(error),clientRequestId=error.client_request_id,
                                 remainingSeconds=max(0,end-time.monotonic()),
                                 policy='read only, abandoned before start, original deadline; no mutation replay')
                if time.monotonic() >= end: raise TimeoutError('Common readiness read deadline exhausted: '+name) from error
                time.sleep(max(0,min(.25,end-time.monotonic())))
            else:
                if time.monotonic() >= end: raise TimeoutError('Common readiness response arrived after deadline: '+name)
                return result
