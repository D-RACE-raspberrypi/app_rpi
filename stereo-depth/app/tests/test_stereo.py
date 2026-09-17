import io
import json
import time
import zipfile

import cv2
import numpy as np
import pytest

from app import Engine, create_app
from stereo import DepthProcessor, DepthSettings, calibrate, object_points


def geometry():
    k = np.array([[500., 0, 320], [0, 500., 240], [0, 0, 1]])
    return dict(K1=k, K2=k.copy(), D1=np.zeros(5), D2=np.zeros(5), R=np.eye(3), T=np.array([[-.06], [0.], [0.]]))


@pytest.mark.parametrize('preset', ['fast', 'balanced', 'quality'])
def test_metric_depth_from_known_disparity(preset):
    rng = np.random.default_rng(17)
    left = rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)
    right = np.roll(left, -20, axis=1)
    processor = DepthProcessor(geometry(), DepthSettings(preset=preset))
    _, _, _, depth, _, valid = processor.process(left, right)
    # Z = f B / d = 500 * .06 / 20 = 1.5 m, including the resized preset.
    assert abs(float(np.nanmedian(depth)) - 1.5) < .025
    assert valid > 60


def test_calibration_recovers_pose_from_projected_board():
    rng = np.random.default_rng(4)
    cal = geometry()
    samples = []
    for _ in range(20):
        rotation = rng.uniform(-.4, .4, 3)
        translation = np.array([rng.uniform(-.15, .02), rng.uniform(-.1, .01), rng.uniform(.55, 1.)])
        left, _ = cv2.projectPoints(object_points(25), rotation, translation, cal['K1'], cal['D1'])
        right, _ = cv2.projectPoints(object_points(25), rotation, translation+cal['T'].ravel(), cal['K2'], cal['D2'])
        samples.append((left, right))
    result, report = calibrate(samples, 25)
    assert abs(report['baseline_mm'] - 60) < .1
    assert report['epipolar_px'] < .01
    assert np.linalg.norm(result['R']-np.eye(3)) < .001


def test_wrong_camera_order_rejected():
    cal = geometry()
    cal['T'] *= -1
    with pytest.raises(ValueError, match='Ordre'):
        DepthProcessor(cal, DepthSettings())


def test_api_workflow_and_export(tmp_path):
    engine = Engine(tmp_path, demo=True)
    client = create_app(engine).test_client()
    assert client.get('/').status_code == 200
    assert client.get('/static/board.html').status_code == 200
    assert client.get('/api/measure?x=0.5&y=0.5').status_code == 400
    assert client.post('/api/settings', json={'near': 5, 'far': 4}).status_code == 400
    assert client.post('/api/settings', json={'near': .5}).status_code == 200
    assert client.post('/api/settings', json={'near': .5}, headers={'Origin':'https://other.example'}).status_code == 403
    assert client.post('/api/calibration/solve', json={}).status_code == 400
    assert client.post('/api/calibration/capture', json={'square_mm':25}).status_code == 400
    engine.cal, engine.report = geometry(), {'test': True}
    engine.depth = np.full((480, 640), 1.5, dtype=np.float32)
    engine.depth[0, 0] = np.nan
    engine.disparity = np.full((480, 640), 20., dtype=np.float32)
    engine.last_depth = time.monotonic()
    assert client.get('/api/measure?x=.5&y=.5').json['distance_m'] == 1.5
    response = client.get('/api/snapshot')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        depth = np.load(io.BytesIO(archive.read('depth-metres.npy')))
        png = cv2.imdecode(np.frombuffer(archive.read('depth-millimetres.png'), np.uint8), cv2.IMREAD_UNCHANGED)
        assert depth[20, 20] == 1.5 and np.isnan(depth[0, 0])
        assert png.dtype == np.uint16 and png[20, 20] == 1500 and png[0, 0] == 0
    engine.last_depth -= 5
    assert client.get('/api/snapshot').status_code == 400


def test_incompatible_calibration_cannot_remain_active(tmp_path):
    engine = Engine(tmp_path)
    engine.cal = geometry()
    engine.report = {'camera_ids':['old-left', 'old-right'], 'focus':1}
    np.savez(tmp_path/'calibration.npz', **engine.cal, report=json.dumps(engine.report))
    engine.camera = type('Camera', (), {'ids':['new-left', 'new-right']})()
    engine.load_calibration()
    assert engine.cal is None and engine.processor is None


def test_trial_produces_depth_without_calibration_and_labels_exports(tmp_path):
    engine = Engine(tmp_path, demo=True)
    client = create_app(engine).test_client()
    assert client.post('/api/trial', json={'enabled': True}).status_code == 200
    engine.follower.config["enabled"]=False  # Stereo tests do not acquire Hailo hardware.
    engine.start()
    try:
        deadline = time.monotonic() + 5
        while engine.depth is None and time.monotonic() < deadline:
            time.sleep(.03)
        assert engine.depth is not None
        status = client.get('/api/status').json
        assert status['trial'] and status['depth_enabled'] and not status['calibrated']
        assert client.get('/api/measure?x=.8&y=.5').json['approximate'] is True
        response = client.get('/api/snapshot')
        assert response.status_code == 200 and 'ESSAI' in response.headers['Content-Disposition']
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            meta = json.loads(archive.read('metadata.json'))
            assert meta['approximate'] is True and meta['calibration'] is None
            assert meta['assumptions']['baseline_mm'] == 65
            depth = np.load(io.BytesIO(archive.read('depth-metres.npy')))
            assert abs(np.nanmedian(depth) - 2.03125) < .04  # 500 * .065 / 16
        assert client.get('/api/calibration/export').status_code == 400
        assert not (tmp_path/'calibration.npz').exists()
    finally:
        engine.stop()
    restored = Engine(tmp_path, demo=True)
    restored.load_calibration()
    assert restored.trial and restored.processor is not None
    client = create_app(restored).test_client()
    assert client.post('/api/settings', json={'preset':'fast'}).status_code == 200
    assert restored.processor.size == (384,288)
    assert client.post('/api/trial', json={'enabled':False}).status_code == 200
    assert restored.processor is None and restored.depth is None
    assert not Engine(tmp_path).trial


def test_trial_preserves_measured_calibration(tmp_path):
    engine = Engine(tmp_path)
    engine.cal, engine.report = geometry(), {'test': True}
    measured = engine.cal
    engine.depth = np.ones((2,2))
    client = create_app(engine).test_client()
    client.post('/api/trial', json={'enabled':True})
    assert engine.cal is measured and engine.depth is None
    assert client.get('/api/status').json['calibrated'] is False
    client.post('/api/trial', json={'enabled':False})
    assert engine.cal is measured and engine.processor is not None
    assert client.get('/api/status').json['calibrated'] is True
    engine.job['state'] = 'running'
    assert client.post('/api/trial', json={'enabled':True}).status_code == 400
    assert not engine.trial


@pytest.mark.parametrize('value', [None, {}, {'enabled':'false'}, {'enabled':1}, {'enabled':True,'extra':1}])
def test_invalid_trial_request(tmp_path, value):
    client = create_app(Engine(tmp_path)).test_client()
    assert client.post('/api/trial', data=json.dumps(value), content_type='application/json').status_code == 400


def test_uniform_noisy_patches_do_not_get_depth():
    rng = np.random.default_rng(8)
    left = rng.integers(99, 102, (480,640,3),dtype=np.uint8)
    right = np.roll(left, -20, axis=1)
    for preset in ['fast','balanced','quality']:
        result = DepthProcessor(geometry(), DepthSettings(preset=preset)).process(left,right)
        assert result[-1] == 0 and np.isnan(result[3]).all()


@pytest.mark.parametrize('preset', ['fast','balanced'])
def test_trial_vertical_alignment_recovers_disparity_and_preserves_calibrated_geometry(preset):
    rng = np.random.default_rng(5)
    left = rng.integers(0,256,(480,640,3),dtype=np.uint8)
    right = cv2.warpAffine(left, np.float32([[1,0,-20],[0,1,25]]), (640,480))
    settings = DepthSettings(preset=preset,trial_y=-25)
    processor = DepthProcessor(geometry(), settings, trial=True)
    _, aligned, _, depth, _, valid = processor.process(left,right)
    assert valid > 55
    assert abs(np.nanmedian(depth)-1.625) < .025
    border = int(25 * depth.shape[0] / 480)
    assert np.isnan(depth[-border:]).all()  # shifted-in border must stay invalid at either resolution
    assert DepthProcessor(geometry(),settings).trial_transform is None


@pytest.mark.parametrize('sensitivity', [50,100])
def test_mutual_matching_rejects_occluded_region(sensitivity):
    rng = np.random.default_rng(72)
    left = rng.integers(0,256,(480,640,3),dtype=np.uint8)
    right = np.roll(left,-20,axis=1)
    right[:,250:350] = rng.integers(0,256,(480,100,3),dtype=np.uint8)
    result = DepthProcessor(geometry(),DepthSettings(texture_sensitivity=sensitivity)).process(left,right)
    assert np.isfinite(result[3][40:-40,285:355]).mean() < .1


def test_sensitivity_recovers_low_contrast_surface():
    rng=np.random.default_rng(81)
    left=cv2.cvtColor(rng.integers(100,109,(480,640),dtype=np.uint8),cv2.COLOR_GRAY2BGR)
    right=np.roll(left,-20,axis=1)
    strict=DepthProcessor(geometry(),DepthSettings(texture_sensitivity=0)).process(left,right)
    tolerant=DepthProcessor(geometry(),DepthSettings(texture_sensitivity=75)).process(left,right)
    assert strict[-1] == 0
    assert tolerant[-1] > 60
    assert abs(np.nanmedian(tolerant[3])-1.5) < .03


def test_sensitivity_validation_and_persistence(tmp_path):
    engine=Engine(tmp_path)
    client=create_app(engine).test_client()
    assert engine.settings.texture_sensitivity == 50
    assert client.post('/api/settings',json={'texture_sensitivity':80}).status_code == 200
    assert Engine(tmp_path).settings.texture_sensitivity == 80
    for value in [-1,101,True,'high',float('nan')]:
        assert client.post('/api/settings',json={'texture_sensitivity':value}).status_code == 400
    assert engine.settings.texture_sensitivity == 80


@pytest.mark.parametrize('preset', ['fast','balanced'])
@pytest.mark.parametrize('offset', [dict(trial_x=14),dict(trial_y=-20),dict(trial_zoom=12),
                                  dict(trial_pitch=2),dict(trial_yaw=-2),dict(trial_roll=3)])
def test_every_manual_slider_changes_only_right_image(preset, offset):
    rng = np.random.default_rng(37)
    left = rng.integers(0,256,(480,640,3),dtype=np.uint8)
    right = np.roll(left,-20,axis=1)
    # Old stereo pose corrections would move both images; they must be ignored in trial mode.
    settings = DepthSettings(preset=preset,tx=2,ty=1,tz=-1,rx=1,ry=2,rz=1,**offset)
    processor = DepthProcessor(geometry(),settings,trial=True)
    l,r,*_ = processor.process(left,right)
    expected_left = cv2.resize(left,processor.size,interpolation=cv2.INTER_AREA)
    expected_right = cv2.resize(right,processor.size,interpolation=cv2.INTER_AREA)
    assert np.array_equal(l,expected_left)
    assert np.mean(r!=expected_right) > .1


def test_manual_reset_restores_identity():
    processor = DepthProcessor(geometry(),DepthSettings(),trial=True)
    assert np.allclose(processor.trial_transform,np.eye(3))


def test_new_manual_offsets_persist_and_export_as_nonmetric(tmp_path):
    engine = Engine(tmp_path,demo=True)
    client = create_app(engine).test_client()
    values = dict(trial_x=10,trial_zoom=5,trial_pitch=.5,trial_yaw=-.4)
    assert client.post('/api/trial',json={'enabled':True}).status_code == 200
    assert client.post('/api/settings',json=values).status_code == 200
    restored = Engine(tmp_path,demo=True)
    assert all(getattr(restored.settings,k)==v for k,v in values.items())
    engine.depth=np.full((480,640),1.5,dtype=np.float32)
    engine.disparity=np.full((480,640),20,dtype=np.float32)
    engine.last_depth=time.monotonic()
    with zipfile.ZipFile(io.BytesIO(client.get('/api/snapshot').data)) as archive:
        meta=json.loads(archive.read('metadata.json'))
        assert meta['assumptions']['metric_scale_valid'] is False
        assert meta['assumptions']['manual_reference']=='unwarped left'
    for values in [dict(trial_x=161),dict(trial_zoom=-61),dict(trial_pitch=11),dict(trial_yaw=float('nan'))]:
        assert client.post('/api/settings',json=values).status_code == 400


def test_rotated_display_depth_measurements_and_exports_match(tmp_path):
    from types import SimpleNamespace
    engine=Engine(tmp_path,demo=True)
    depth=np.full((480,640),2.,np.float32)
    depth[240:]=4.
    disparity=np.full_like(depth,15.)
    disparity[240:]=7.5
    def process(left,right):
        return left,right,left.copy(),depth,disparity,100.
    engine.processor=SimpleNamespace(size=(640,480),process=process,range_depth=depth,settings=DepthSettings())
    engine.cal,engine.report=geometry(),{'test':True}
    engine.load_calibration=lambda:None
    engine.follower.config["enabled"]=False  # Stereo tests do not acquire Hailo hardware.
    engine.start()
    try:
        deadline=time.monotonic()+5
        while engine.depth is None and time.monotonic()<deadline:time.sleep(.03)
        client=create_app(engine).test_client()
        assert client.get('/api/status').json['display_rotation_deg']==180
        assert client.get('/api/measure?x=.5&y=.1').json['distance_m']==4.
        assert client.get('/api/measure?x=.5&y=.9').json['distance_m']==2.
        with zipfile.ZipFile(io.BytesIO(client.get('/api/snapshot').data)) as archive:
            exported=np.load(io.BytesIO(archive.read('depth-metres.npy')))
            disp=np.load(io.BytesIO(archive.read('disparity-pixels.npy')))
            assert np.array_equal(exported,depth[::-1,::-1])
            assert np.array_equal(disp,disparity[::-1,::-1])
            assert json.loads(archive.read('metadata.json'))['image_rotation_deg']==180
        # Acquisition arrays, including calibration input, keep their original orientation.
        assert np.array_equal(depth[:240],np.full((240,640),2.,np.float32))
        assert engine.cal['T'][0,0]==-.06
    finally:
        engine.stop()


def test_orientation_preserves_camera_order_and_setting(tmp_path):
    engine=Engine(tmp_path)
    left=np.arange(12,dtype=np.uint8).reshape(3,4)
    right=left+20
    assert np.array_equal(engine.orient(left),left[::-1,::-1])
    assert np.array_equal(engine.orient(right),right[::-1,::-1])
    engine.rotate_display=False
    engine.save_settings()
    restored=Engine(tmp_path)
    assert restored.rotate_display is False
    assert np.array_equal(restored.orient(left),left)


def test_range_depth_keeps_valid_returns_beyond_display_limit():
    rng=np.random.default_rng(15)
    left=rng.integers(0,256,(480,640,3),dtype=np.uint8)
    right=np.roll(left,-6,axis=1)
    processor=DepthProcessor(geometry(),DepthSettings(preset='quality',far=4))
    _,_,_,display,_,_=processor.process(left,right)
    assert np.nanmedian(processor.range_depth)==pytest.approx(5,abs=.1)
    assert np.isfinite(processor.range_depth).sum()>1000
    assert np.isnan(display).mean()>.95
