"""Photography custody/uncertainty and measured-data gates; no live game."""
import copy
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from skyrim_autotest import photography as p, config, platform
from skyrim_autotest import runner  # Resolve normal runtime before test configuration.

SPEC={'referenceTag':'sample-npc'}
BASE={'plugin':'fixture.esp','localId':'1234'}
REF='0xFF001001'
INC={'sessionId':'session','loadGeneration':1,'runtimeHandle':42}


def png(width=1920,height=1080):
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,0,0,0,0))+
            chunk(b'IDAT',zlib.compress((b'\0'+b'\x80'*width)*height))+chunk(b'IEND',b''))


class Session:
    def __init__(self,path):
        self.dir=path;self.state={'id':'test','testProfile':'owned','gameplayBootstrap':{'completed':True}}
    def save(self):pass
    def log(self,*a,**kw):pass


class Backend:
    def __init__(self,path):
        self.s=Session(path);self.calls=[];self.failure=None;self.width=1920
        self.n={'protocol':'photography-readback/1','phase':'skse_main_thread_task','freezeTime':False,'ui':{'paused':False,'menusVisible':True,'blockingMenu':False},
                'actor':{'reference':REF,'runtimeHandle':42,'restrained':True,'aiEnabled':True,'collisionsEnabled':True,
                         'position':[0.,0.,0.],'angles':[0.,0.,0.],'bound':{'center':[0.,0.,100.],'radius':100.}},
                'camera':{'world':{'translation':[0.,1000.,100.]},'worldToCam':[0.]*16,'frustum':{'near':1.},
                          'eyeFrustums':[{},{}],'viewport':[0.,1.,1.,0.],
                          'projectedBoundCorners':[{'projected':True,'uvDepth':[.5,.5,1.]} for _ in range(8)]}}
        self.camera={'freeCam':True,'freeCamOwned':True,'freeCamBackend':'vr-state','camAngles':'freeCameraState',
                     'stateId':3,'camX':0.,'camY':1000.,'camZ':100.,'camPitch':0.,'camYaw':3.141592653589793}
    def guard_world(self):pass
    def remaining(self):return 20
    def pause(self,v):pass
    def resolve(self,v):return '0x01001234'
    def pap(self,*a,**kw):
        self.calls.append(('pap',a,kw))
        if self.failure:raise RuntimeError(self.failure)
        if a[1]=='PlaceAtMe':return {'formId':REF}
        if a[1]=='GetBodyMorph':return 0.
        return None
    def call(self,tool,args):
        self.calls.append((tool,copy.deepcopy(args)))
        if self.failure:raise RuntimeError(self.failure)
        if tool=='photography_readback':return copy.deepcopy(self.n)
        if tool=='camera':
            if args['action']=='get':return copy.deepcopy(self.camera)
            if args['action']=='freecam':self.camera.update(freeCam=args['on'],stateId=3 if args['on'] else 13)
            return {'queued':False}
        if tool=='inspect':
            if args.get('kind')=='lights':return {'scope':'scene','truncated':False,'coverage':{'truncated':False},'count':0,'lights':[]}
            return {'refs':[{'formType':'NPC_','position':[0.,0.,0.],'rotation':[0.,0.,0.]}]}
        if tool=='capture':
            path=Path(args['outDir'])/'photography/original'/(args['checkpointId']+'.png');path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(png(self.width));return {'ok':True,'provider':'provider','uiExcluded':True,'inconclusive':False,
                'degraded':[],'sceneMismatch':False,'path':str(path)}
        raise AssertionError(tool)


class PhotographyTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.b=Backend(Path(temp.name))
        self.addCleanup(patch.stopall)
        patch.object(config.P,'value',{'photography':{'captureProvider':'provider','distanceGameUnits':1000,'maximumPhotos':16},
                                     'fixture_actor_base_allowlist':[BASE]}).start()
        self.anchor=patch.object(p,'anchor',return_value=(INC,{'baseForm':'0x01001234','loaded3D':True},{})).start()
        p.state(self.b)['actors'][SPEC['referenceTag']]={'status':'created','reference':REF,'base':'0x01001234','incarnation':INC}
        self.f={'targetRegion':'full-body','azimuthDegrees':0,'azimuthBasis':'actor-front-clockwise','elevationDegrees':0,
                'rollDegrees':0,'comparisonGroup':'pair','framingPolicy':'fixed-camera-per-comparison-group',
                'includeWholeTarget':True,'marginFraction':.15,'background':'existing-cell','hud':'hidden'}
        self.req={'action':'capture_fixture_photo','actor':SPEC,'photoId':'baseline','format':'png','minimumWidthPixels':1920,
                  'minimumHeightPixels':1080,'configuration':{'morphKey':'OWN','expectedMorphs':{'Ear':0.}},
                  'requireActualMetadata':True,'settleSeconds':1,'qualityPolicy':'original-render-no-upscale'}
        measured={'actor':{'reference':REF,'sex':'male','weight':50.,'race':'0x000CDD84','loaded3D':True},'nativePhotography':self.b.n,
                  'lighting':{'sampledSceneLights':[]},'cell':'0x00123456'}
        patch.object(p,'measure',side_effect=lambda *a:copy.deepcopy(measured)).start()
        self.morphs=patch.object(p,'read_morphs',return_value={'Ear':0.}).start()
        s=p.state(self.b);s['initialCamera']={'stateId':13};s['initialUi']=copy.deepcopy(self.b.n['ui'])
        s['groups']['pair']={'status':'framed','framing':copy.deepcopy(self.f),'actorTag':SPEC['referenceTag'],
                             'actor':copy.deepcopy(self.b.n['actor']),'signature':p.camera_signature(self.b.n),
                             'lighting':{'sampledSceneLights':[]},
                             'command':{'action':'drive','x':0.,'y':1000.,'z':100.,'pitch':0.,'yaw':self.b.camera['camYaw']}}
        s['currentGroup']='pair'

    def test_original_capture_keeps_measured_metadata_and_hash(self):
        r=p.photo(self.b,self.req);self.assertTrue(r['photo']['saved'])
        a=r['artifact'];self.assertEqual(a['sha256'],hashlib.sha256(Path(a['image']).read_bytes()).hexdigest())
        self.assertFalse(a['renderedContentVerified']);self.assertEqual(a['morphs'],{'Ear':0.})

    def test_lost_capture_response_is_not_replayed(self):
        self.b.failure='lost response'
        with self.assertRaises(RuntimeError):p.photo(self.b,self.req)
        self.b.failure=None
        with self.assertRaisesRegex(ValueError,'already attempted'):p.photo(self.b,self.req)
        self.assertEqual(len([c for c in self.b.calls if c[0]=='capture']),1)

    def test_low_resolution_preserves_original_and_failure(self):
        self.b.width=640
        with self.assertRaisesRegex(ValueError,'resolution'):p.photo(self.b,self.req)
        self.assertEqual(p.state(self.b)['photos']['baseline']['status'],'unavailable_or_uncertain')

    def test_expected_morph_not_substituted_for_observation(self):
        self.morphs.return_value={'Ear':.9}
        with self.assertRaisesRegex(ValueError,'morph configuration'):p.photo(self.b,self.req)
        self.assertFalse(any(c[0]=='capture' for c in self.b.calls))

    def test_changed_baseline_camera_stops_before_capture(self):
        p.state(self.b)['groups']['pair']['signature']['worldToCam'][0]=1.
        with self.assertRaisesRegex(ValueError,'framing changed'):p.photo(self.b,self.req)

    def test_reference_incarnation_change_stops(self):
        self.anchor.return_value=({**INC,'runtimeHandle':99},{'baseForm':'0x01001234','loaded3D':True},{})
        with self.assertRaisesRegex(ValueError,'incarnation'):p.actor(self.b,SPEC)

    def test_create_never_replays_uncertain_spawn(self):
        p.state(self.b)['actors'].clear()
        req={'action':'create_fixture_actor','actorBase':BASE,'referenceTag':'sample-npc',
             'placement':{'basis':'player-horizontal-forward','forwardGameUnits':480,'rightGameUnits':-160},
             'scope':'owned-disposable-profile','onUncertainCompletion':'stop-without-replay'}
        original=self.b.pap
        def uncertain(*args,**kwargs):
            if args[1]=='PlaceAtMe':raise TimeoutError('could have spawned')
            return original(*args,**kwargs)
        self.b.pap=uncertain
        with self.assertRaises(TimeoutError):p.create(self.b,req)
        with self.assertRaisesRegex(ValueError,'already attempted'):p.create(self.b,req)

    def test_unknown_base_and_unready_profile_never_spawn(self):
        p.state(self.b)['actors'].clear()
        config.P.value['fixture_actor_base_allowlist']=[]
        with self.assertRaises(ValueError):p.create(self.b,{'actorBase':BASE})
        self.b.s.state['gameplayBootstrap']['completed']=False
        with self.assertRaises(ValueError):p.enabled(self.b)
        self.assertFalse(self.b.calls)

    def test_foreign_or_changed_camera_is_not_restored(self):
        self.b.camera['freeCamOwned']=False
        with self.assertRaisesRegex(ValueError,'another owner'):p.restore(self.b)
        self.assertEqual(len(self.b.calls),1)

    def test_restore_verifies_normal_state_and_unchanged_ui(self):
        r=p.restore(self.b);self.assertTrue(r['camera']['restored']);self.assertTrue(r['hud']['restored'])
        self.assertFalse(any(c[0] in ('console','input') for c in self.b.calls))

    def test_same_pair_reuses_fixed_command(self):
        self.assertTrue(p.frame(self.b,{'actor':SPEC,'framing':self.f})['camera']['target']['inFrame'])
        self.assertEqual([c for c in self.b.calls if c[0]=='camera' and c[1]['action']=='drive'][0][1],
                         p.state(self.b)['groups']['pair']['command'])

    def test_changed_actor_cannot_reframe_pair(self):
        self.b.n['actor']['position'][0]=20.
        with self.assertRaisesRegex(ValueError,'never reframe'):p.frame(self.b,{'actor':SPEC,'framing':self.f})
        self.assertFalse(any(c[0]=='camera' and c[1]['action']=='drive' for c in self.b.calls))

    def test_offscreen_bound_does_not_pass(self):
        self.b.n['camera']['projectedBoundCorners'][0]['uvDepth'][0]=1.1
        self.assertFalse(p.in_frame(self.b.n,.15))

    def test_false_not_numeric_success(self):
        self.assertFalse(p.close_numbers({'a':True},{'a':1}))

    def test_malformed_or_native_provider_rejected(self):
        for c in ('auto','native','../x'):
            with self.assertRaises(ValueError):p.configuration({'captureProvider':c,'distanceGameUnits':1000,'maximumPhotos':16})
        req=copy.deepcopy(self.req);req['photoId']='../target'
        with self.assertRaises(ValueError):p.validate('object.perform',req)

    def test_uncertain_morph_set_blocks_later_mutation(self):
        self.b.failure='setter completion unknown'
        req={'action':'update_fixture_body_model','actor':SPEC}
        with self.assertRaises(RuntimeError):p.perform(self.b,req)
        self.b.failure=None
        with self.assertRaisesRegex(ValueError,'Prior NPC mutation'):p.perform(self.b,req)

    def test_collector_detects_original_tampering(self):
        result=p.photo(self.b,self.req);Path(result['artifact']['image']).write_bytes(b'tampered')
        def copy_file(path,*args,**kwargs):return {'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        with self.assertRaisesRegex(ValueError,'changed'):p.collect(self.b.s,copy_file)

    def test_valid_semantic_actions_are_routed_without_mod_name(self):
        platform.validate({'operation':'object.perform','request':self.req})
        platform.validate({'operation':'world.read','request':{'observation':'fixture-body-morphs','actor':SPEC,'key':'OWN','morphs':['Ear']}})

    def test_freeze_and_actual_menu_block_capture_measurement(self):
        self.b.n['freezeTime']=True
        with self.assertRaisesRegex(ValueError,'freeze state'):p.native(self.b,p.state(self.b)['actors']['sample-npc'])
        self.b.n['freezeTime']=False;self.b.n['ui']['blockingMenu']=True
        with self.assertRaises(ValueError):p.native(self.b,p.state(self.b)['actors']['sample-npc'])

    def test_existing_pixels_never_adopted(self):
        file=self.b.s.dir/'photography-artifacts/photography/original/baseline.png'
        file.parent.mkdir(parents=True);file.write_bytes(png())
        with self.assertRaisesRegex(ValueError,'already exists'):p.photo(self.b,self.req)
        self.assertFalse(any(c[0]=='capture' for c in self.b.calls))

    def test_index_includes_unrun_plans_and_derivative_preview(self):
        from skyrim_autotest import photo_index
        import json
        steps=[{'tool':'platform','args':{'request':{'action':'frame_fixture_actor','framing':{'comparisonGroup':'pair'}}}},
               *[{'tool':'platform','args':{'request':{'action':'capture_fixture_photo','photoId':v}}} for v in ('baseline','changed')]]
        file=self.b.s.dir/'scenario.json';file.write_text(json.dumps({'steps':steps}),encoding='utf-8')
        self.b.s.state['scenarioHash']=hashlib.sha256(file.read_bytes()).hexdigest()
        p.photo(self.b,self.req);index=photo_index.write(self.b.s)
        self.assertEqual([s['status'] for s in index['shots']],['verified','not_run'])
        self.assertEqual(len(index['pairs']),1);self.assertTrue(index['contactSheet']['derivedPreview'])
        file.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'scenario changed'):photo_index.write(self.b.s)

    def test_thumbnail_reads_original_filter_and_colour(self):
        from skyrim_autotest.photo_index import thumbnail
        from tests.test_assisted_capture import png as rgb_png
        self.assertEqual(thumbnail(rgb_png(),2,2),bytearray(b'\x12\x34\x56'*4))


if __name__=='__main__':unittest.main()
